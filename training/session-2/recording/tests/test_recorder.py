"""Recorder behavior with local Python children only; never invokes Claude."""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "record_demo.py"
SPEC = importlib.util.spec_from_file_location("session2_record_demo_tested", SOURCE)
RECORDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECORDER)


def pid_running(pid: int) -> bool:
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.GetExitCodeProcess.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.restype = ctypes.c_int
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error in (0, 87):  # no process for the PID
                return False
            raise OSError(error, "Cannot inspect owned test child")
        try:
            exit_code = ctypes.c_uint32()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    status = Path(f"/proc/{pid}/stat")
    if status.is_file():
        # A terminated orphan can remain as a zombie until init reaps it.
        if status.read_text().rsplit(")", 1)[1].split()[0] == "Z":
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s2-recorder-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.destination = self.root / "recordings"
        self.env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    def record(self, script: str, *, prompt: str = "Синтетичний промпт\n",
               timeout: float = 5, deny_taskkill: bool = False):
        # The extra process bounds each test even if recorder cleanup regresses.
        worker_source = """
import importlib.util, json, os, pathlib, subprocess, sys
data = json.loads(sys.stdin.read())
spec = importlib.util.spec_from_file_location('tested_recorder', data['source'])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if data['deny_taskkill']:
    actual_run = subprocess.run
    def deny_owned_taskkill(command, *args, **kwargs):
        if command[0] == 'taskkill':
            return subprocess.CompletedProcess(command, 5)
        return actual_run(command, *args, **kwargs)
    module.subprocess.run = deny_owned_taskkill
meta = module.record([sys.executable, '-u', '-c', data['script']], data['prompt'],
    pathlib.Path(data['workspace']), pathlib.Path(data['destination']), 'take',
    data['timeout'], dict(os.environ))
print(json.dumps(meta))
"""
        payload = {"source": str(SOURCE), "script": script, "prompt": prompt,
                   "workspace": str(self.workspace), "destination": str(self.destination),
                   "timeout": timeout, "deny_taskkill": deny_taskkill}
        worker = subprocess.Popen([sys.executable, "-u", "-c", worker_source],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                  env=self.env, start_new_session=os.name != "nt")
        try:
            stdout, stderr = worker.communicate(json.dumps(payload), timeout=20)
        except subprocess.TimeoutExpired:
            RECORDER.stop_process(worker)
            self.fail("Recorder exceeded the test's outer 20-second timeout")
        self.assertEqual(worker.returncode, 0, stderr)
        return json.loads(stdout)

    def events(self):
        return [json.loads(line) for line in
                (self.destination / "take.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_success_preserves_prompt_visible_events_and_terminal_metrics(self):
        prompt = "Перевір суму 25,55.\nSQL не виконуй.\n"
        terminal = {
            "type": "result", "subtype": "success", "is_error": False,
            "result": "Статичне рев'ю завершено.", "duration_ms": 1234,
            "total_cost_usd": 0.0123,
            "modelUsage": {"observed-model": {
                "inputTokens": 10, "cacheReadInputTokens": 20,
                "cacheCreationInputTokens": 30, "outputTokens": 40}},
        }
        script = f"""
import json, sys, time
prompt = sys.stdin.read()
print(json.dumps({{"type":"user", "prompt":prompt}}, ensure_ascii=False), flush=True)
time.sleep(0.05)
print(json.dumps({{"type":"assistant", "message":{{"content":[{{"type":"text", "text":"Читаю контракт"}}]}}}}, ensure_ascii=False), flush=True)
time.sleep(0.05)
print(json.dumps({terminal!r}, ensure_ascii=False), flush=True)
print("diagnostic only", file=sys.stderr)
"""
        meta = self.record(script, prompt=prompt)
        events = self.events()
        self.assertEqual(meta["status"], "success")
        self.assertEqual(meta["exitCode"], 0)
        self.assertEqual(meta["eventCount"], 3)
        self.assertIsNone(meta["reason"])
        self.assertEqual((self.destination / "take.prompt.txt").read_text(encoding="utf-8"), prompt)
        self.assertEqual(events[0]["event"]["prompt"], prompt)
        self.assertEqual(events[-1]["event"], terminal)
        elapsed = [row["elapsed"] for row in events]
        self.assertEqual(elapsed, sorted(elapsed))
        self.assertTrue(all(value >= 0 for value in elapsed))
        self.assertGreater(elapsed[-1], elapsed[0])
        self.assertGreaterEqual(meta["durationSeconds"], elapsed[-1])
        self.assertEqual(meta["rawSha256"], hashlib.sha256(
            (self.destination / "take.jsonl").read_bytes()).hexdigest())
        self.assertEqual(json.loads((self.destination / "take.meta.json").read_text(encoding="utf-8")), meta)
        self.assertIn("diagnostic only", (self.destination / "take.stderr.txt").read_text(encoding="utf-8"))

    def test_missing_terminal_result_fails_even_with_zero_exit(self):
        meta = self.record('import sys; sys.stdin.read(); print(\'{"type":"assistant"}\')')
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["reason"], "missing_result")
        self.assertEqual(meta["exitCode"], 0)

    def test_nonzero_exit_fails_despite_success_result(self):
        meta = self.record('import sys; sys.stdin.read(); print(\'{"type":"result","subtype":"success"}\'); sys.exit(7)')
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["reason"], "process_exit")
        self.assertEqual(meta["exitCode"], 7)
        self.assertEqual(meta["resultSubtype"], "success")

    def test_terminal_error_is_not_success(self):
        meta = self.record('import sys; sys.stdin.read(); print(\'{"type":"result","subtype":"error_during_execution","is_error":true}\')')
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["reason"], "result_error")

    def test_terminal_success_requires_explicit_false_error_flag(self):
        meta = self.record('import sys; sys.stdin.read(); print(\'{"type":"result","subtype":"success"}\')')
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["reason"], "result_error")

    def test_malformed_json_retained_and_fails_even_after_success(self):
        meta = self.record('import sys; sys.stdin.read(); print("not json"); print(\'{"type":"result","subtype":"success"}\')')
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["reason"], "invalid_json")
        self.assertEqual(self.events()[0]["event"], {"type": "recorder_unparsed", "text": "not json"})

    def test_json_without_event_object_records_failure_instead_of_crashing(self):
        meta = self.record('import sys; sys.stdin.read(); print("null"); print("[]"); print(\'{"type":"result","subtype":"success"}\')')
        self.assertEqual(meta["status"], "failed")
        self.assertEqual(meta["reason"], "invalid_event")
        self.assertEqual(self.events()[0]["event"], {"type": "recorder_invalid_event", "value": None})
        self.assertEqual(self.events()[1]["event"]["value"], [])

    def test_any_existing_take_file_refuses_overwrite(self):
        self.destination.mkdir()
        for suffix in ("jsonl", "stderr.txt", "prompt.txt", "meta.json"):
            with self.subTest(suffix=suffix):
                existing = self.destination / f"take.{suffix}"
                existing.write_bytes(b"existing take must survive")
                with self.assertRaises(FileExistsError):
                    RECORDER.record([sys.executable, "-c", 'raise RuntimeError("must never start")'],
                                    "prompt", self.workspace, self.destination, "take", 5, self.env)
                self.assertEqual(existing.read_bytes(), b"existing take must survive")
                self.assertEqual(list(self.destination.iterdir()), [existing])
                existing.unlink()

    @unittest.skipUnless(os.name != "nt" or os.environ.get("SESSION2_RUN_PROCESS_TREE_TEST") == "1",
                         "Windows: opt in where taskkill can terminate this test's own child tree")
    def test_timeout_terminates_owned_child_tree(self):
        script = """
import json, pathlib, subprocess, sys, time
sys.stdin.read()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
pathlib.Path('child.pid').write_text(str(child.pid))
print(json.dumps({'type':'system','message':'child started'}), flush=True)
time.sleep(120)
"""
        pid = None
        started = time.monotonic()
        try:
            meta = self.record(script, timeout=1)
            self.assertEqual(meta["status"], "failed")
            self.assertEqual(meta["reason"], "timeout")
            self.assertTrue(meta["terminationConfirmed"])
            self.assertLess(time.monotonic() - started, 15)
            pid = int((self.workspace / "child.pid").read_text())
            deadline = time.monotonic() + 3
            while pid_running(pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(pid_running(pid), "Recorder left its own child process alive")
        finally:
            # A failed assertion still cleans only the exact child created by this test.
            if pid is None and (self.workspace / "child.pid").exists():
                pid = int((self.workspace / "child.pid").read_text())
            if pid is not None and pid_running(pid):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True, timeout=10)
                else:
                    os.kill(pid, signal.SIGKILL)

    def test_timeout_also_applies_when_child_never_reads_large_prompt(self):
        started = time.monotonic()
        meta = self.record("import time; time.sleep(120)", prompt="x" * 2_000_000, timeout=1)
        self.assertEqual(meta["status"], "failed")
        self.assertTrue(meta["reason"].startswith("timeout"))
        self.assertLess(time.monotonic() - started, 15)

    @unittest.skipUnless(os.name == "nt" and os.environ.get("SESSION2_RUN_PROCESS_TREE_TEST") == "1",
                         "Windows own-child taskkill permission is needed for test cleanup")
    def test_denied_taskkill_returns_failed_metadata_without_stdout_deadlock(self):
        script = """
import json, pathlib, subprocess, sys, time
sys.stdin.read()
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
pathlib.Path('child.pid').write_text(str(child.pid))
print(json.dumps({'type':'system','message':'child inherited stdout'}), flush=True)
time.sleep(120)
"""
        started = time.monotonic()
        try:
            meta = self.record(script, timeout=1, deny_taskkill=True)
            self.assertEqual(meta["status"], "failed")
            self.assertEqual(meta["reason"], "timeout_termination_failed")
            self.assertFalse(meta["terminationConfirmed"])
            self.assertLess(time.monotonic() - started, 15)
        finally:
            pid_file = self.workspace / "child.pid"
            if pid_file.exists():
                owned_child = int(pid_file.read_text())
                if pid_running(owned_child):
                    result = subprocess.run(["taskkill", "/PID", str(owned_child), "/T", "/F"],
                                            capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
