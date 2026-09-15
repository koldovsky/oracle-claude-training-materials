"""Поведінкові тести PreToolUse через справжній stdin/exit protocol; без БД."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SESSION = Path(__file__).resolve().parents[1]
HOOK = SESSION / "extensions" / ".claude" / "hooks" / "sql_guard.py"
DEMO = HOOK.with_name("demo.py")


class SqlGuardProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="s2 paths з пробілом ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "lab").mkdir()
        self.file = self.root / "lab" / "пакет.sql"
        self.original = "SELECT 1 FROM dual;\n"
        self.file.write_text(self.original, encoding="utf-8")

    def run_hook(self, payload, *, raw=False, with_project=True):
        env = dict(os.environ)
        env.pop("CLAUDE_PROJECT_DIR", None)
        if with_project:
            env["CLAUDE_PROJECT_DIR"] = str(self.root)
        data = payload if raw else json.dumps(payload).encode("utf-8")
        return subprocess.run(
            [sys.executable, str(HOOK)], input=data, capture_output=True,
            env=env, timeout=10, check=False,
        )

    def write_payload(self, content, path=None):
        return {
            "hook_event_name": "PreToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(path or self.file), "content": content},
        }

    def edit_payload(self, old, new, **extra):
        return {
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {
                "file_path": str(self.file), "old_string": old,
                "new_string": new, **extra,
            },
        }

    def assert_decision(self, result, code):
        self.assertEqual(result.returncode, code, result.stderr.decode("utf-8"))
        self.assertEqual(result.stdout, b"", "Не можна обходити звичайні дозволи через allow JSON")
        if code == 2:
            self.assertIn(b"SQL guard:", result.stderr)
        else:
            self.assertEqual(result.stderr, b"")

    def test_allows_regular_static_sql_and_empty_write(self):
        for sql in [self.original, "", "SELECT truncation_note FROM s2_orders;",
                    "CREATE OR REPLACE PACKAGE s2_settlement AS END;\n/",
                    "ALTER TABLE S2_ORDERS ADD (note VARCHAR2(50));"]:
            with self.subTest(sql=sql):
                self.assert_decision(self.run_hook(self.write_payload(sql)), 0)
        self.assertEqual(self.file.read_text(encoding="utf-8"), self.original)

    def test_blocks_destructive_sql_case_whitespace_and_comments(self):
        for sql in ["DROP TABLE S2_ORDERS;", "truncate\n table S2_ORDERS;",
                    "AlTeR\tSyStEm FLUSH SHARED_POOL;",
                    "ALTER /* навчання */ SYSTEM FLUSH SHARED_POOL;",
                    "ALTER -- навчання\nSYSTEM FLUSH SHARED_POOL;",
                    "BEGIN EXECUTE IMMEDIATE 'DROP TABLE S2_ORDERS'; END;",
                    "BEGIN EXECUTE IMMEDIATE 'DR' || 'OP TABLE S2_ORDERS'; END;",
                    "BEGIN EXECUTE IMMEDIATE 'TRUN'||'CATE TABLE S2_ORDERS'; END;"]:
            with self.subTest(sql=sql):
                self.assert_decision(self.run_hook(self.write_payload(sql)), 2)
        self.assertEqual(self.file.read_text(encoding="utf-8"), self.original)

    def test_comment_and_string_false_positives_are_conservative(self):
        for sql in ["-- DROP TABLE example\nSELECT 1 FROM dual;",
                    "SELECT 'TRUNCATE' FROM dual;"]:
            with self.subTest(sql=sql):
                self.assert_decision(self.run_hook(self.write_payload(sql)), 2)

    def test_allows_non_sql_and_paths_outside_lab(self):
        for path in [self.root / "README.md", self.root / ".claude" / "settings.json",
                     self.root / "other.sql", self.root / "laboratory" / "example.sql"]:
            with self.subTest(path=path):
                self.assert_decision(self.run_hook(self.write_payload("DROP TABLE x;", path)), 0)

    def test_uppercase_extension_and_normalized_parent_path_are_checked(self):
        for path in [self.root / "lab" / "TEST.SQL", self.root / "lab" / ".." / "lab" / "x.sql"]:
            with self.subTest(path=path):
                self.assert_decision(self.run_hook(self.write_payload("DROP TABLE x;", path)), 2)

    def test_allows_valid_edit_without_modifying_file(self):
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2")), 0)
        self.assertEqual(self.file.read_text(encoding="utf-8"), self.original)

    def test_edit_inspects_result_beyond_changed_fragment(self):
        self.file.write_text("DROP TABLE S2_ORDERS;\nSELECT 1 FROM dual;\n", encoding="utf-8")
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2")), 2)

    def test_edit_combines_existing_and_new_tokens(self):
        self.file.write_text("DRX TABLE S2_ORDERS;\n", encoding="utf-8")
        self.assert_decision(self.run_hook(self.edit_payload("X", "OP")), 2)

    def test_allows_edit_removing_all_destructive_content(self):
        self.file.write_text("DROP TABLE S2_ORDERS;\n", encoding="utf-8")
        self.assert_decision(self.run_hook(self.edit_payload("DROP TABLE S2_ORDERS;", self.original)), 0)

    def test_ambiguous_edit_requires_replace_all(self):
        self.file.write_text("SELECT 1 FROM dual;\nSELECT 1 FROM dual;\n", encoding="utf-8")
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2")), 2)
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2", replace_all=True)), 0)
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "TRUNCATE", replace_all=True)), 2)

    def test_unmatched_and_empty_edits_block(self):
        for old in ["NOT FOUND", "", "   "]:
            with self.subTest(old=old):
                self.assert_decision(self.run_hook(self.edit_payload(old, "SELECT 2")), 2)

    def test_missing_file_and_invalid_utf8_block(self):
        self.file.unlink()
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2")), 2)
        self.file.write_bytes(b"\xff\xfe\x00")
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2")), 2)

    def test_missing_or_invalid_write_fields_block(self):
        for field, value in [("file_path", None), ("file_path", ""), ("file_path", 1),
                             ("content", None), ("content", []), ("content", "\x00")]:
            with self.subTest(field=field, value=value):
                payload = self.write_payload(self.original)
                payload["tool_input"][field] = value
                self.assert_decision(self.run_hook(payload), 2)
        payload = self.write_payload(self.original)
        del payload["tool_input"]["content"]
        self.assert_decision(self.run_hook(payload), 2)

    def test_missing_or_invalid_edit_fields_block(self):
        for field, value in [("old_string", None), ("new_string", 123),
                             ("replace_all", "false"), ("replace_all", 1)]:
            with self.subTest(field=field, value=value):
                payload = self.edit_payload("SELECT 1", "SELECT 2")
                payload["tool_input"][field] = value
                self.assert_decision(self.run_hook(payload), 2)
        payload = self.edit_payload("SELECT 1", "SELECT 2")
        del payload["tool_input"]["new_string"]
        self.assert_decision(self.run_hook(payload), 2)

    def test_invalid_json_and_event_envelope_block(self):
        for data in [b"{", b"", b"null", b"[]", b"1", b"\xff", b"{}",
                     b'{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":[]}']:
            with self.subTest(data=data):
                self.assert_decision(self.run_hook(data, raw=True), 2)
        payload = self.write_payload(self.original)
        payload["hook_event_name"] = "PostToolUse"
        self.assert_decision(self.run_hook(payload), 2)

    def test_utf8_bom_payload_and_file_are_supported(self):
        data = b"\xef\xbb\xbf" + json.dumps(self.write_payload(self.original)).encode("utf-8")
        self.assert_decision(self.run_hook(data, raw=True), 0)
        self.file.write_text(self.original, encoding="utf-8-sig")
        self.assert_decision(self.run_hook(self.edit_payload("SELECT 1", "SELECT 2")), 0)

    def test_missing_project_or_relative_path_block(self):
        self.assert_decision(self.run_hook(self.write_payload(self.original), with_project=False), 2)
        self.assert_decision(self.run_hook(self.write_payload(self.original, "lab/file.sql")), 2)

    def test_payload_size_limit_blocks(self):
        self.assert_decision(self.run_hook(self.write_payload("x" * 2_000_001)), 2)

    def test_other_tool_is_out_of_scope_without_permission_override(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "sql /nolog"}}
        self.assert_decision(self.run_hook(payload, with_project=False), 0)

    def test_demo_runs_actual_hook_and_passes(self):
        result = subprocess.run([sys.executable, str(DEMO)], capture_output=True,
                                timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8") + result.stderr.decode("utf-8"))
        self.assertEqual(result.stdout.count(b"PASS |"), 7)
        self.assertNotIn(b"FAIL |", result.stdout)
        self.assertEqual(self.file.read_text(encoding="utf-8"), self.original)


if __name__ == "__main__":
    unittest.main()
