"""Перевірка рішень runner за відповідями SQLcl; без запуску SQLcl чи доступу до БД."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


RUNNER = Path(__file__).resolve().parents[1] / "run-lab.py"


class SqlclRunnerTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("session2_runner_test", RUNNER)
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        self.temp = tempfile.TemporaryDirectory(prefix="session2-runner-test-")
        self.workspace = Path(self.temp.name).resolve() / "робоча тека"
        self.assertTrue(self.workspace.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temp.cleanup)
        (self.workspace / "lab").mkdir(parents=True)
        for filename, _ in self.runner.ACTIONS.values():
            (self.workspace / "lab" / filename).write_text("-- test fixture\n", encoding="utf-8")

    def run_action(self, action, stdout, *, stderr="", returncode=0, exception=None):
        output, errors = io.StringIO(), io.StringIO()
        result = subprocess.CompletedProcess(["fake-sql"], returncode, stdout, stderr)
        argv = [str(RUNNER), action, "--workspace", str(self.workspace), "--connection", "test-only"]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(self.runner.shutil, "which", return_value="fake-sql"), \
             mock.patch.object(self.runner.subprocess, "run", return_value=result,
                               side_effect=exception) as run, \
             redirect_stdout(output), redirect_stderr(errors):
            code = self.runner.main()
        return code, output.getvalue(), errors.getvalue(), run

    def assert_failed(self, result):
        code, stdout, stderr, _ = result
        self.assertNotEqual(code, 0, stdout + stderr)
        self.assertNotIn("SQLCL_RUN_PASS", stdout)
        self.assertIn("SQLCL_FAIL", stderr)

    def test_valid_result_for_each_action_uses_workspace_connection_and_closed_stdin(self):
        for action, (filename, marker) in self.runner.ACTIONS.items():
            with self.subTest(action=action):
                if action not in {"baseline", "verify"}:
                    marker += ": перевірку завершено."
                code, output, errors, run = self.run_action(action, f"SQLcl banner\n{marker}\n")
                self.assertEqual(code, 0, output + errors)
                self.assertIn("SQLCL_RUN_PASS " + action, output)
                command = run.call_args.args[0]
                self.assertEqual(command, ["fake-sql", "-S", "-name", "test-only", "@lab/" + filename])
                self.assertEqual(run.call_args.kwargs["cwd"], self.workspace)
                self.assertEqual(run.call_args.kwargs["input"], "")

    def test_zero_exit_without_an_actual_success_marker_cannot_pass(self):
        marker = self.runner.ACTIONS["verify"][1]
        for output in ["", "Connected.\n", "[PASS] only one case\n",
                       "prompt " + marker + "\n", "NOT_" + marker + "\n",
                       marker + " BUT_FAILED\n", marker.replace("checks=18", "checks=1"),
                       marker.replace("unexpected=0", "unexpected=5")]:
            with self.subTest(output=output):
                self.assert_failed(self.run_action("verify", output))
        self.assert_failed(self.run_action("verify", "", stderr=marker))
        self.assert_failed(self.run_action("compile", "NOT_COMPILE_OK\n"))

    def test_zero_exit_with_success_marker_and_reported_error_cannot_pass(self):
        marker = self.runner.ACTIONS["verify"][1]
        error_lines = [
            "ORA-20999: acceptance failed",
            "  ORA-20999: acceptance failed",
            "SP2-0310: unable to open file",
            "\tSP2-0310: unable to open file",
            "Error starting at line : 1",
            "Error report -",
            "ERROR at line 1:",
            "java.lang.RuntimeException: SQLcl startup failed",
            "java.sql.SQLException: connection failed",
            'Exception in thread "main" java.lang.NoClassDefFoundError: MissingClass',
        ]
        for line in error_lines:
            for channel in ("stdout", "stderr"):
                with self.subTest(line=line, channel=channel):
                    stdout = marker + "\n" + (line if channel == "stdout" else "")
                    stderr = line if channel == "stderr" else ""
                    self.assert_failed(self.run_action("verify", stdout, stderr=stderr))

    def test_failed_exit_timeout_and_launch_error_cannot_pass(self):
        marker = self.runner.ACTIONS["verify"][1]
        self.assert_failed(self.run_action("verify", marker, returncode=1))
        self.assert_failed(self.run_action("verify", marker, returncode=255))
        self.assert_failed(self.run_action(
            "verify", marker, exception=subprocess.TimeoutExpired("fake-sql", 120)))
        self.assert_failed(self.run_action("verify", marker, exception=OSError("test launch error")))

    def test_one_actions_success_cannot_satisfy_another_action(self):
        baseline_marker = self.runner.ACTIONS["baseline"][1]
        verify_marker = self.runner.ACTIONS["verify"][1]
        self.assert_failed(self.run_action("verify", baseline_marker))
        self.assert_failed(self.run_action("baseline", verify_marker))
        self.assert_failed(self.run_action("compile", "INSTALL_OK: installed\n"))


if __name__ == "__main__":
    unittest.main()
