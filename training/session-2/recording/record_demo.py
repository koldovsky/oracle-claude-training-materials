#!/usr/bin/env python3
"""Record an actual Session 2 Claude CLI run with per-event timestamps.

Raw files stay in the ignored .rehearsal directory. Use build_rehearsal.py to
export a reviewed, sanitized, offline playback page.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

SESSION = Path(__file__).resolve().parents[1]


def stop_process(process: subprocess.Popen) -> bool:
    """Terminate only this recorder's process tree on a timeout/interruption."""
    tree_stopped = True
    if os.name == "nt":
        try:
            result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            tree_stopped = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            tree_stopped = False
        if not tree_stopped and process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    if os.name != "nt":
        # The parent may exit on TERM while one of its children ignores it.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return tree_stopped


def record(command: list[str], prompt: str, workspace: Path, destination: Path,
           name: str, timeout: int, env: dict[str, str]) -> dict:
    paths = {suffix: destination / f"{name}.{suffix}" for suffix in
             ("jsonl", "stderr.txt", "prompt.txt", "meta.json")}
    if any(path.exists() for path in paths.values()):
        raise FileExistsError("Recording name already exists; choose a new --name.")
    destination.mkdir(parents=True, exist_ok=True)
    with paths["prompt.txt"].open("x", encoding="utf-8") as prompt_output:
        prompt_output.write(prompt)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    events: queue.Queue = queue.Queue()
    with paths["jsonl"].open("x", encoding="utf-8") as output, paths["stderr.txt"].open("x", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=stderr, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1,
                                   start_new_session=os.name != "nt")

        def read_lines():
            try:
                for line in process.stdout:
                    events.put((time.monotonic() - started, line))
            finally:
                events.put(None)

        input_errors: list[str] = []

        def write_prompt():
            # A child that stops reading must not prevent the recorder timeout.
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except (BrokenPipeError, OSError, ValueError) as error:
                input_errors.append(type(error).__name__)
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError, ValueError):
                    pass

        thread = threading.Thread(target=read_lines, daemon=True)
        writer = threading.Thread(target=write_prompt, daemon=True)
        thread.start()
        writer.start()
        terminal = None
        count = 0
        reason = None
        termination_confirmed = None
        try:
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    reason = "timeout"
                    termination_confirmed = stop_process(process)
                    break
                try:
                    entry = events.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    continue
                if entry is None:
                    break
                elapsed, line = entry
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "recorder_unparsed", "text": line.rstrip()}
                    reason = "invalid_json"
                if not isinstance(event, dict):
                    event = {"type": "recorder_invalid_event", "value": event}
                    reason = reason or "invalid_event"
                output.write(json.dumps({"elapsed": round(elapsed, 6), "event": event}, ensure_ascii=False) + "\n")
                output.flush()
                count += 1
                if event.get("type") == "result":
                    terminal = event
            if process.poll() is None:
                try:
                    process.wait(timeout=max(0.1, timeout - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    reason = "timeout"
                    termination_confirmed = stop_process(process)
        except KeyboardInterrupt:
            reason = "interrupted"
            termination_confirmed = stop_process(process)
        finally:
            writer.join(timeout=2)
            thread.join(timeout=2)
            # close() can wait forever on the reader's lock if a surviving child
            # inherited stdout and taskkill was denied by the host sandbox.
            if not thread.is_alive():
                process.stdout.close()
            else:
                termination_confirmed = False
                reason = reason or "stdout_stream_open"
    if termination_confirmed is False:
        reason = (reason or "interrupted") + "_termination_failed"
    if reason is None and input_errors:
        reason = "prompt_delivery_failed"
    if reason is None and process.returncode != 0:
        reason = "process_exit"
    if reason is None and terminal is None:
        reason = "missing_result"
    result_ok = bool(terminal and terminal.get("subtype") == "success" and terminal.get("is_error") is False)
    if reason is None and not result_ok:
        reason = "result_error"
    passed = process.returncode == 0 and result_ok and reason is None
    metadata = {
        "schemaVersion": 1, "name": name, "kind": "claude", "startedAt": started_at,
        "durationSeconds": round(time.monotonic() - started, 6),
        "exitCode": process.returncode, "eventCount": count,
        "status": "success" if passed else "failed", "reason": reason,
        "terminationConfirmed": termination_confirmed,
        "resultSubtype": terminal.get("subtype") if terminal else None,
        "rawSha256": hashlib.sha256(paths["jsonl"].read_bytes()).hexdigest(),
        "promptFile": paths["prompt.txt"].name,
    }
    paths["meta.json"].write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="New recording name; never overwrites an existing take")
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=SESSION / ".rehearsal/recordings")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--max-budget-usd", type=float, default=3)
    parser.add_argument("--with-sqlcl-mcp", action="store_true", help="Allow only the workspace's SQLcl MCP, for requested read-only SQL")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.name):
        parser.error("--name must use lowercase letters, digits, underscores or hyphens")
    if args.timeout <= 0 or args.max_budget_usd <= 0:
        parser.error("Timeout and budget must be positive")
    workspace = args.workspace.resolve()
    if not all((workspace / relative).is_file() for relative in
               ("lab/SPEC.md", "lab/settlement-starter.pkb.sql", ".claude/settings.json", "CLAUDE.md")):
        parser.error("Use a generated Session 2 workspace from setup-workspace.py")
    executable = shutil.which("claude")
    if not executable:
        parser.error("Claude Code not found in PATH")
    if not args.prompt.is_file():
        parser.error("Prompt file not found")
    mcp_config = '{"mcpServers":{}}'
    if args.with_sqlcl_mcp:
        config_path = workspace / ".mcp.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config != {"mcpServers": {"sqlcl": {"command": "sql", "args": ["-mcp"]}}}:
            parser.error("Expected only the generated SQLcl MCP configuration")
        mcp_config = str(config_path)
    available_tools = "Read,Glob,Grep,Skill,Agent,Write,Edit"
    allowed_tools = available_tools + (",mcp__sqlcl__*" if args.with_sqlcl_mcp else "")
    command = [executable, "-p", "--no-session-persistence", "--output-format", "stream-json", "--verbose",
               "--include-hook-events", "--setting-sources", "project", "--strict-mcp-config",
               "--mcp-config", mcp_config, "--permission-mode", "acceptEdits", "--tools", available_tools,
               "--allowedTools", allowed_tools, "--max-budget-usd", str(args.max_budget_usd),
               "--append-system-prompt", "Authorized Session 2 recording with synthetic training files. "
               "Stay inside the current workspace. Never read parent directories, credentials, personal configuration or trainer answers. "
               "Do not change tests, starter files, hooks or tool permissions. Do not bypass a blocked operation. "
               + ("SQLcl MCP may run only the requested read-only SELECT. " if args.with_sqlcl_mcp else "No SQL execution or external tools are available. ")
               + "Report only observed actions and distinguish static analysis from executed tests."]
    env = {**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "PYTHONIOENCODING": "utf-8"}
    if os.name == "nt" and "CLAUDE_CODE_GIT_BASH_PATH" not in env:
        bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if bash.is_file():
            env["CLAUDE_CODE_GIT_BASH_PATH"] = str(bash)
    try:
        metadata = record(command, args.prompt.read_text(encoding="utf-8"), workspace,
                          args.output_dir.resolve(), args.name, args.timeout, env)
    except (OSError, ValueError) as error:
        print(f"RECORDING_FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, indent=2, ensure_ascii=False))
    print("RECORDING_PASS" if metadata["status"] == "success" else "RECORDING_FAIL")
    return 0 if metadata["status"] == "success" else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
