#!/usr/bin/env python3
"""Репетиція JSON-протоколу hook без Oracle і без змін робочих SQL-файлів."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    hook = Path(__file__).with_name("sql_guard.py")
    with tempfile.TemporaryDirectory(prefix="s2-hook-demo-") as temp_dir:
        root = Path(temp_dir)
        lab = root / "lab"
        lab.mkdir()
        target = lab / "demo.sql"
        original = "SELECT 1 FROM dual;\n"
        target.write_text(original, encoding="utf-8")
        base = {"hook_event_name": "PreToolUse", "tool_name": "Write"}
        scenarios = [
            ("Write SELECT", {**base, "tool_input": {
                "file_path": str(target), "content": original}}, 0),
            ("Write DROP", {**base, "tool_input": {
                "file_path": str(target), "content": "DROP TABLE S2_ORDERS;"}}, 2),
            ("Write dynamic TRUNCATE", {**base, "tool_input": {
                "file_path": str(target),
                "content": "BEGIN EXECUTE IMMEDIATE 'TRUNCATE TABLE S2_ORDERS'; END;"}}, 2),
            ("Edit SELECT", {**base, "tool_name": "Edit", "tool_input": {
                "file_path": str(target), "old_string": "SELECT 1", "new_string": "SELECT 2"}}, 0),
            ("Edit ALTER SYSTEM", {**base, "tool_name": "Edit", "tool_input": {
                "file_path": str(target), "old_string": "SELECT 1 FROM dual;",
                "new_string": "ALTER SYSTEM FLUSH SHARED_POOL;"}}, 2),
            ("Неповний JSON Write", {**base, "tool_input": {"file_path": str(target)}}, 2),
        ]
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        failed = False
        for title, payload, expected in scenarios:
            result = subprocess.run(
                [sys.executable, str(hook)], input=json.dumps(payload).encode("utf-8"),
                capture_output=True, env=env, check=False, timeout=10,
            )
            passed = result.returncode == expected and result.stdout == b""
            failed = failed or not passed
            print(f"{'PASS' if passed else 'FAIL'} | {title} | exit={result.returncode}, очікується {expected}")
            if expected == 2 or not passed:
                print(result.stderr.decode("utf-8", errors="replace").strip())
        unchanged = target.read_text(encoding="utf-8") == original
        print(f"{'PASS' if unchanged else 'FAIL'} | тимчасовий SQL-файл не змінено")
        if failed or not unchanged:
            return 1
    print("Демо завершено: hook перевірив JSON; SQL не виконувався, робочі файли не змінено.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
