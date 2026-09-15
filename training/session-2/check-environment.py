#!/usr/bin/env python3
"""Read-only checks. --database uses the existing SQLcl connection; no resets or DDL."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--connection", default="train")
    args = parser.parse_args()
    errors = 0
    print(f"Python {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print("FAIL Python 3.10+ required")
        errors += 1
    for tool, flag, pattern in (("git", "--version", r"git version \d"), ("claude", "--version", r"\d+\.\d+\.\d+"), ("sql", "-V", r"SQLcl: Release \d")):
        executable = shutil.which(tool)
        if not executable:
            print(f"FAIL {tool} missing from PATH")
            errors += 1
            continue
        try:
            result = subprocess.run([executable, flag], capture_output=True, text=True, timeout=45, encoding="utf-8", errors="replace")
            version = next((line.strip() for line in (result.stdout + result.stderr).splitlines() if re.search(pattern, line)), "")
            ok = result.returncode == 0 and bool(version)
            print(f"{'OK' if ok else 'FAIL'} {tool}: {version or 'no valid version output'}")
            errors += not ok
        except (OSError, subprocess.TimeoutExpired):
            print(f"FAIL {tool} did not complete")
            errors += 1
    if args.database:
        sql = shutil.which("sql")
        if not sql:
            return 1
        query = """whenever sqlerror exit failure rollback
set echo off feedback off heading off pagesize 0 verify off
select 'SESSION2_DB_OK ' || user from dual;
select 'HR_ROWS ' || count(*) from hr.employees;
select 'CO_ORDERS ' || count(*) from co.orders;
exit success
"""
        try:
            result = subprocess.run([sql, "-S", "-name", args.connection], input=query, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            lines = [line.strip() for line in result.stdout.splitlines() if re.match(r"^(SESSION2_DB_OK|HR_ROWS|CO_ORDERS) ", line.strip())]
            values = dict(line.split(" ", 1) for line in lines)
            allowed_users = {"TRAINER", *(f"TRAINEE{i}" for i in range(1, 6))}
            ok = (result.returncode == 0 and len(lines) == 3
                  and values.get("SESSION2_DB_OK") in allowed_users
                  and values.get("HR_ROWS") == "107"
                  and values.get("CO_ORDERS") == "1950")
            print("\n".join(lines) if ok else "FAIL database: check saved connection, wallet and network")
            errors += not ok
        except (OSError, subprocess.TimeoutExpired):
            print("FAIL database: process did not complete within 60 seconds")
            errors += 1
    print("PREFLIGHT_PASS" if not errors else f"PREFLIGHT_FAIL {errors}")
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
