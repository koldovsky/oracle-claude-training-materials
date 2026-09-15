#!/usr/bin/env python3
"""SQLcl runner for terminals/automation with explicit stdin and result validation."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
ACTIONS = {
    "install": ("install.sql", "INSTALL_OK"),
    "baseline": ("verify-baseline.sql", "BASELINE_CONFIRMED: checks=18, known_failures=5, unexpected=0"),
    "compile": ("compile.sql", "COMPILE_OK"),
    "verify": ("verify.sql", "ACCEPTANCE_PASS: checks=18, unexpected=0"),
    "reset": ("reset-starter.sql", "RESET_OK"),
    "cleanup": ("cleanup.sql", "CLEANUP_OK"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parent / "workspace")
    parser.add_argument("--connection", default="train")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    filename, marker = ACTIONS[args.action]
    if not (workspace / "lab" / filename).is_file():
        parser.error(f"Missing lab/{filename} in {workspace}")
    executable = shutil.which("sql")
    if not executable:
        parser.error("SQLcl not found in PATH")
    try:
        result = subprocess.run([executable, "-S", "-name", args.connection, "@lab/" + filename],
                                input="", capture_output=True, text=True, encoding="utf-8", errors="replace",
                                cwd=workspace, timeout=120)
    except subprocess.TimeoutExpired:
        print("SQLCL_FAIL: timeout after 120 seconds", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"SQLCL_FAIL: could not start SQLcl: {error}", file=sys.stderr)
        return 1
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    errors = re.search(
        r'(?m)^\s*(?:ORA-\d+|SP2-\d+|Error starting\b|Error report\b|ERROR at line\b|'
        r'(?:Exception in thread "[^"]+"\s+)?(?:java|javax|oracle)\.[A-Za-z0-9_.$]*(?:Exception|Error)\b)',
        result.stdout + "\n" + result.stderr,
    )
    lines = [line.strip() for line in result.stdout.splitlines()]
    if args.action in {"baseline", "verify"}:
        marker_found = marker in lines
    else:
        marker_found = any(line == marker or line.startswith(marker + ":") for line in lines)
    if result.returncode != 0 or not marker_found or errors:
        print("SQLCL_FAIL: nonzero exit, reported error, or missing expected result marker", file=sys.stderr)
        return 1
    print("SQLCL_RUN_PASS " + args.action)
    return 0


if __name__ == "__main__":
    sys.exit(main())
