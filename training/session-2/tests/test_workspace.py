"""Перевірки робочого каталогу й preflight: справжній Git, підставні відповіді SQLcl."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import venv


SESSION = Path(__file__).resolve().parents[1]
SETUP = SESSION / "setup-workspace.py"
CHECK = SESSION / "check-environment.py"


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_git_env():
    env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "BASH_ENV"):
        env.pop(key, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def bash_executable():
    found = shutil.which("bash")
    if found:
        return found
    if os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


@unittest.skipUnless(shutil.which("git"), "Потрібен Git для інтеграційної перевірки")
class WorkspaceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="acord-session2-workspace-")
        self.root = Path(self.temp.name).resolve()
        # Область рекурсивного прибирання — лише створений каталог у системному temp.
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temp.cleanup)
        self.env = isolated_git_env()

    def create_workspace(self, destination, interpreter=None):
        return subprocess.run(
            [str(interpreter or sys.executable), str(SETUP), str(destination)],
            capture_output=True, env=self.env, timeout=60, check=False,
        )

    def assert_process_ok(self, result):
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, output)

    def git(self, destination, *args):
        result = subprocess.run(
            ["git", "-C", str(destination), *args], capture_output=True,
            env=self.env, timeout=20, check=False,
        )
        self.assert_process_ok(result)
        return result.stdout.decode("utf-8", errors="replace")

    def test_fresh_workspace_has_clean_commit_edit_diff_and_refuses_overwrite(self):
        destination = self.root / "participant workspace"
        first = self.create_workspace(destination)
        self.assert_process_ok(first)
        self.assertIn(b"WORKSPACE_READY", first.stdout)
        self.assertEqual(self.git(destination, "status", "--porcelain"), "")
        baseline = self.git(destination, "rev-parse", "HEAD").strip()
        self.assertEqual(self.git(destination, "rev-list", "--count", "HEAD").strip(), "1")

        working_body = destination / "lab/settlement.pkb.sql"
        edited = working_body.read_bytes() + b"\n-- participant change retained\n"
        working_body.write_bytes(edited)
        diff = self.git(destination, "diff", "--", "lab/settlement.pkb.sql")
        self.assertIn("+-- participant change retained", diff)

        second = self.create_workspace(destination)
        self.assertNotEqual(second.returncode, 0, second.stdout.decode("utf-8", errors="replace"))
        self.assertIn(b"Already exists", second.stderr)
        self.assertEqual(working_body.read_bytes(), edited)
        self.assertEqual(self.git(destination, "rev-parse", "HEAD").strip(), baseline)
        self.assertEqual(self.git(destination, "diff", "--", "lab/settlement.pkb.sql"), diff)

        copied_names = {p.relative_to(destination).as_posix() for p in destination.rglob("*")
                        if ".git" not in p.relative_to(destination).parts}
        answer_files = {"settlement-reference.pkb.sql", "apply-reference.sql", "EXPECTED-FINDINGS.md"}
        self.assertFalse(any("trainer" in Path(p).parts or Path(p).name in answer_files
                             for p in copied_names))
        self.assertFalse(any(part in {".wallet", ".secrets", "CREDENTIALS.txt"}
                             for p in copied_names for part in Path(p).parts))

    def test_source_private_sentinels_are_excluded_from_workspace_and_git(self):
        source = self.root / "course source"
        source.mkdir()
        shutil.copytree(SESSION / "lab", source / "lab", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(SESSION / "extensions/.claude", source / "extensions/.claude",
                        ignore=shutil.ignore_patterns("__pycache__"))
        # Це вигадані маркери тесту, не облікові дані чи матеріали користувача.
        private_paths = ("trainer/reference-only.txt", ".wallet/DO_NOT_COPY",
                         "setup/.secrets/DO_NOT_COPY", "CREDENTIALS.txt")
        for relative in private_paths:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("PRIVATE_TEST_SENTINEL_ONLY", encoding="utf-8")
        destination = self.root / "isolated participant"
        setup = load_script("session2_setup_private_test", SETUP)
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(setup, "SOURCE", source), \
             mock.patch.object(sys, "argv", [str(SETUP), str(destination)]), \
             mock.patch.dict(os.environ, self.env, clear=True), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            result = setup.main()
        self.assertEqual(result, 0, stdout.getvalue() + stderr.getvalue())
        tracked = self.git(destination, "ls-files")
        for relative in private_paths:
            self.assertFalse((destination / relative).exists(), relative)
            self.assertNotIn(relative, tracked)
        for file in destination.rglob("*"):
            if file.is_file() and ".git" not in file.relative_to(destination).parts:
                self.assertNotIn(b"PRIVATE_TEST_SENTINEL_ONLY", file.read_bytes(), str(file))
        self.assertEqual(self.git(destination, "status", "--porcelain"), "")

    @unittest.skipUnless(bash_executable(), "Потрібен Bash для виконання згенерованої команди hook")
    def test_generated_hook_runs_exact_interpreter_with_spaces_and_unicode(self):
        interpreter_root = self.root / "Python інтерпретатор space"
        venv.EnvBuilder(with_pip=False).create(interpreter_root)
        executable = interpreter_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self.assertTrue(executable.is_file())
        destination = self.root / "Учасник workspace"
        created = self.create_workspace(destination, executable)
        self.assert_process_ok(created)

        settings = json.loads((destination / ".claude/settings.json").read_text(encoding="utf-8"))
        hook = settings["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(shlex.split(hook["command"])[0], executable.as_posix())
        self.assertEqual(hook["shell"], "bash")
        env = {**self.env, "CLAUDE_PROJECT_DIR": destination.as_posix()}
        target = destination / "lab/settlement.pkb.sql"
        before = target.read_bytes()
        for proposed, expected_code in [("SELECT 1 FROM dual;", 0), ("DROP TABLE S2_ORDERS;", 2)]:
            with self.subTest(proposed=proposed):
                payload = {
                    "hook_event_name": "PreToolUse", "tool_name": "Write",
                    "tool_input": {"file_path": str(target), "content": proposed},
                }
                result = subprocess.run(
                    [bash_executable(), "--noprofile", "--norc", "-c", hook["command"]],
                    input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    capture_output=True, env=env, timeout=30, check=False,
                )
                self.assertEqual(result.returncode, expected_code,
                                 result.stderr.decode("utf-8", errors="replace"))
                self.assertEqual(result.stdout, b"")
        self.assertEqual(target.read_bytes(), before)


class EnvironmentPreflightTests(unittest.TestCase):
    def setUp(self):
        self.check = load_script("session2_check_test", CHECK)

    def run_preflight(self, database_stdout, *, database_code=0, database_error=None,
                      missing_tool=None, version_error=None):
        database_calls = []
        versions = {
            "git": "git version 2.50.0",
            "claude": "2.1.0 (Claude Code)",
            "sql": "SQLcl: Release 26.2.2.0 Production",
        }

        def which(tool):
            return None if tool == missing_tool else "fake-" + tool

        def run(command, **kwargs):
            tool = command[0].removeprefix("fake-")
            if "input" in kwargs:
                database_calls.append((command, kwargs))
                if database_error:
                    raise database_error
                return subprocess.CompletedProcess(command, database_code, database_stdout, "")
            if version_error and tool == version_error[0]:
                return subprocess.CompletedProcess(command, version_error[1], version_error[2], "")
            return subprocess.CompletedProcess(command, 0, versions[tool], "")

        output = io.StringIO()
        with mock.patch.object(sys, "argv", [str(CHECK), "--database", "--connection", "test-only"]), \
             mock.patch.object(self.check.shutil, "which", side_effect=which), \
             mock.patch.object(self.check.subprocess, "run", side_effect=run), \
             redirect_stdout(output):
            code = self.check.main()
        return code, output.getvalue(), database_calls

    def assert_failed(self, result):
        code, output, _ = result
        self.assertNotEqual(code, 0, output)
        self.assertNotIn("PREFLIGHT_PASS", output)

    def test_valid_training_accounts_and_expected_counts_pass(self):
        for user in ["TRAINER", *(f"TRAINEE{i}" for i in range(1, 6))]:
            with self.subTest(user=user):
                code, output, calls = self.run_preflight(
                    f"SQLcl banner\nSESSION2_DB_OK {user}\nHR_ROWS 107\nCO_ORDERS 1950\n")
                self.assertEqual(code, 0, output)
                self.assertIn("PREFLIGHT_PASS", output)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0][-2:], ["-name", "test-only"])
                query = calls[0][1]["input"].upper()
                self.assertNotRegex(query, r"\b(CREATE|ALTER|DROP|TRUNCATE|INSERT|UPDATE|DELETE)\b")

    def test_success_exit_with_wrong_account_or_counts_is_rejected(self):
        cases = [
            "SESSION2_DB_OK ADMIN\nHR_ROWS 107\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK TRAINEE6\nHR_ROWS 107\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK TRAINEE0\nHR_ROWS 107\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK trainer\nHR_ROWS 107\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 0\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 107\nCO_ORDERS 1949\n",
        ]
        for stdout in cases:
            with self.subTest(stdout=stdout):
                self.assert_failed(self.run_preflight(stdout))

    def test_success_exit_with_incomplete_duplicate_or_malformed_output_is_rejected(self):
        cases = [
            "",
            "Connected.\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 107\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 107\nHR_ROWS 107\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 107\nCO_ORDERS 1950\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 107\nCO_ORDERS null\n",
            "SESSION2_DB_OK TRAINER\nHR_ROWS 107 rows\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK TRAINER extra\nHR_ROWS 107\nCO_ORDERS 1950\n",
            "SESSION2_DB_OK=TRAINER\nHR_ROWS=107\nCO_ORDERS=1950\n",
            "ORA-01017: invalid login\n",
        ]
        for stdout in cases:
            with self.subTest(stdout=stdout):
                self.assert_failed(self.run_preflight(stdout))

    def test_valid_markers_with_failed_exit_or_timeout_cannot_pass(self):
        valid = "SESSION2_DB_OK TRAINER\nHR_ROWS 107\nCO_ORDERS 1950\n"
        self.assert_failed(self.run_preflight(valid, database_code=1))
        self.assert_failed(self.run_preflight(valid, database_code=255))
        self.assert_failed(self.run_preflight(
            valid, database_error=subprocess.TimeoutExpired("fake-sql", 60)))
        self.assert_failed(self.run_preflight(valid, database_error=OSError("test spawn failed")))

    def test_broken_local_tool_cannot_be_hidden_by_good_database_result(self):
        valid = "SESSION2_DB_OK TRAINER\nHR_ROWS 107\nCO_ORDERS 1950\n"
        for missing in ("git", "claude", "sql"):
            with self.subTest(missing=missing):
                self.assert_failed(self.run_preflight(valid, missing_tool=missing))
        for version_error in [("sql", 0, "Could not find or load main class SqlCli"),
                              ("claude", 1, "2.1.0 (Claude Code)")]:
            with self.subTest(version_error=version_error):
                self.assert_failed(self.run_preflight(valid, version_error=version_error))


if __name__ == "__main__":
    unittest.main()
