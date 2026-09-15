"""Standalone lesson and practice bundle checks; no network, Claude, or Oracle calls."""

import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "build_rehearsal.py"
spec = importlib.util.spec_from_file_location("session2_lesson_export", SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def lesson():
    return {
        **{key: {"title": key, "blocks": []}
           for key in ("intro", "preparation", "closing", "glossary")},
        "sections": {key: {"before": [], "after": []} for key in build.LESSON_SECTION_IDS},
    }


def recording():
    return {
        "schemaVersion": 1, "title": "Запис", "date": "2026-09-15", "description": "Опис",
        "method": ["Фактичні події."],
        "sections": [{"id": "baseline", "title": "Початок", "slot": "Вступ",
                      "goal": "Перевірити", "takeaway": "Доказ", "runIds": ["one"]}],
        "runs": [{
            "id": "one", "title": "Прогін", "subtitle": "", "kind": "claude",
            "sourceName": "one.jsonl", "model": "example-model", "version": "1.0",
            "status": "Успішний прогін", "timing": "recorded",
            "frames": [{"kind": "prompt", "text": "Перевір.", "elapsed": 0},
                       {"kind": "assistant", "text": "Готово.", "elapsed": 1.25}],
            "metrics": {"durationSeconds": 1.2, "costUsd": 0.01, "inputTokens": 42,
                        "outputTokens": 4, "initialInputTokens": 40, "toolCalls": 0},
        }],
    }


class LessonExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="session2-lesson-export-")
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temp.cleanup)

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def public_tree(self):
        repo = self.root / "course"
        for name in build.PRACTICE_FILES:
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(build.REPO / name, target)
        return repo

    def test_nested_lesson_resolves_real_sources_and_preserves_teaching_code(self):
        raw = lesson()
        raw["preparation"]["blocks"] = [{
            "type": "details", "title": "Читати код", "open": False, "blocks": [
                {"type": "heading", "text": "Hook"},
                {"type": "source", "path": "training/session-2/extensions/.claude/hooks/sql_guard.py",
                 "title": "Повний код", "language": "python"},
                {"type": "table", "headers": ["Стан", "Код"], "rows": [["дозволено", "0"], ["відмова", "2"]]},
                {"type": "steps", "items": ["Прочитати.", "Запустити."]},
            ],
        }]
        raw["sections"]["skill"]["before"] = [{"type": "source", "path": "lab/SPEC.md",
                                                "title": "Контракт", "language": "markdown"}]
        loaded = build.load_lesson(self.write_json("lesson.json", raw))
        details = loaded["preparation"]["blocks"][0]
        self.assertFalse(details["open"])
        self.assertEqual(details["blocks"][2]["rows"], [["дозволено", "0"], ["відмова", "2"]])
        source = details["blocks"][1]
        self.assertEqual(source["text"], (build.REPO / source["path"]).read_text(encoding="utf-8"))
        self.assertIn("#!/usr/bin/env python3", source["text"])
        self.assertEqual(loaded["sections"]["skill"]["before"][0]["path"],
                         "training/session-2/lab/SPEC.md")
        self.assertEqual(json.loads(build.embedded_json(loaded)), loaded)
        sanitizer = build.Sanitizer(public_code=True)
        self.assertEqual(sanitizer.text("D:/projects/private/account.txt"),
                         "<local-path>/projects/private/account.txt")
        self.assertEqual(sanitizer.text(str(build.REPO / "credentials.txt")),
                         "<workspace>/credentials.txt")

    def test_lesson_rejects_unsafe_paths_bad_structure_and_active_links(self):
        for path in ("../trainer/reference.sql", "/etc/passwd", "C:/private.txt",
                     "training/session-2/trainer/settlement-reference.pkb.sql",
                     "training/session-2/workspace/lab/settlement.pkb.sql",
                     "training/session-2/lab/../lab/SPEC.md",
                     "training/session-2/extensions/.claude/settings.local.json"):
            with self.subTest(path=path), self.assertRaises(build.BuildError):
                build.lesson_blocks([{"type": "source", "path": path, "title": "Код", "language": "sql"}])
        for block in (
            {"type": "details", "title": "Код", "open": "false", "blocks": []},
            {"type": "table", "headers": ["a", "b"], "rows": [["a"]]},
            {"type": "list", "items": [{"html": "<script>"}]},
            {"type": "link", "text": "Open", "url": "javascript:alert(1)"},
            {"type": "link", "text": "Open", "url": "file:///C:/private.txt"},
            {"type": "link", "text": "Open", "url": "https://name:password@example.invalid/"},
            {"type": "unknown"},
        ):
            with self.subTest(block=block), self.assertRaises(build.BuildError):
                build.lesson_blocks([block])
        raw = lesson()
        del raw["sections"]["mcp"]
        with self.assertRaises(build.BuildError):
            build.load_lesson(self.write_json("missing-section.json", raw))

    def test_public_paths_reject_linked_files_and_linked_ancestor(self):
        repo = self.public_tree()
        name = "training/session-2/lab/SPEC.md"
        for linked in (repo / name, repo / "training/session-2/lab"):
            with self.subTest(linked=linked):
                original = Path.is_symlink
                with mock.patch.object(Path, "is_symlink",
                                       lambda path: path == linked or original(path)):
                    with self.assertRaises(build.BuildError):
                        build.public_file(name, repo)

    def test_optional_lesson_preserves_legacy_raw_build_and_explicit_missing_is_error(self):
        source = self.root / "one.jsonl"
        source.write_text(json.dumps({"type": "result", "subtype": "success",
                                     "is_error": False, "result": "Готово."}), encoding="utf-8")
        manifest = {"schemaVersion": 1, "title": "Legacy", "sections": [],
                    "runs": [{"id": "one", "kind": "claude", "source": "one.jsonl"}]}
        path = self.write_json("sources.json", manifest)
        data = build.build_data(path)
        self.assertNotIn("lesson", data)
        self.assertEqual(data["runs"][0]["frames"][0]["text"], "Готово.")
        self.assertEqual(data["practiceArchive"]["filename"], "session-2-practice.zip")
        with self.assertRaises(build.BuildError):
            build.build_data(path, self.root / "absent-lesson.json")

    def test_archive_is_deterministic_allowlisted_and_source_starter_is_exact(self):
        repo = self.public_tree()
        private = repo / "training/session-2/extensions/.claude/settings.local.json"
        private.write_text("PRIVATE_SENTINEL", encoding="utf-8")
        (repo / "training/session-2/lab/private.sql").write_text("PRIVATE_SENTINEL", encoding="utf-8")
        first = build.build_practice_archive(repo)
        second = build.build_practice_archive(repo)
        self.assertEqual(first, second)
        payload = base64.b64decode(first["base64"], validate=True)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), first["sha256"])
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), first["files"])
            self.assertEqual(set(archive.namelist()), {"START-HERE.md", *build.PRACTICE_FILES})
            self.assertFalse(any("private" in name or "trainer" in name or "workspace/" in name
                                 or name.endswith(".html") for name in archive.namelist()))
            for info in archive.infolist():
                self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))
                self.assertEqual(info.external_attr >> 16, 0o100644)
                self.assertNotIn(b"PRIVATE_SENTINEL", archive.read(info))
            starter = archive.read("training/session-2/lab/settlement.pkb.sql")
            self.assertEqual(starter, archive.read("training/session-2/lab/settlement-starter.pkb.sql"))
            self.assertEqual(starter, (build.REPO / "training/session-2/lab/settlement.pkb.sql").read_bytes())

    def test_archive_refuses_solution_body_and_secret_in_public_source(self):
        repo = self.public_tree()
        body = repo / "training/session-2/lab/settlement.pkb.sql"
        original = body.read_bytes()
        body.write_bytes(original + b"\n-- changed solution\n")
        with self.assertRaisesRegex(build.BuildError, "unchanged starter"):
            build.build_practice_archive(repo)
        body.write_bytes(original)
        script = repo / "training/session-2/setup-workspace.py"
        script.write_text(script.read_text(encoding="utf-8") + "\napi_key = 'fake-secret-for-test'\n", encoding="utf-8")
        with self.assertRaisesRegex(build.BuildError, "Private values"):
            build.build_practice_archive(repo)

    def test_extracted_archive_creates_clean_independent_workspace(self):
        bundle = build.build_practice_archive()
        destination = self.root / "Робоча тека"
        destination.mkdir()
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(bundle["base64"]))) as archive:
            archive.extractall(destination)
        result = subprocess.run([sys.executable, "training/session-2/setup-workspace.py"],
                                cwd=destination, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workspace = destination / "training/session-2/workspace"
        self.assertTrue((workspace / ".claude/hooks/sql_guard.py").is_file())
        for arguments, expected in ((["status", "--porcelain"], ""), (["rev-list", "--count", "HEAD"], "1\n")):
            git = subprocess.run(["git", "-C", str(workspace), *arguments],
                                 capture_output=True, text=True, timeout=15)
            self.assertEqual(git.returncode, 0, git.stderr)
            self.assertEqual(git.stdout, expected)
        original = (workspace / "lab/settlement.pkb.sql").read_bytes()
        again = subprocess.run([sys.executable, "training/session-2/setup-workspace.py"],
                               cwd=destination, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=15)
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual((workspace / "lab/settlement.pkb.sql").read_bytes(), original)

    def test_from_data_preserves_run_facts_and_replaces_old_lesson_archive(self):
        original = recording()
        raw = copy.deepcopy(original)
        raw.update(lesson={"old": True}, practiceArchive={"base64": "not-a-real-archive"},
                   privateProfile={"password": "never-export-this"})
        raw["runs"][0]["metadata"] = {"password": "never-export-this"}
        raw["runs"][0]["frames"][1]["signature"] = "never-export-this"
        path = self.write_json("published.json", raw)
        current = lesson()
        current["intro"]["blocks"] = [{"type": "p", "text": "Поточний урок."}]
        output = build.build_from_data(path, self.write_json("lesson.json", current))
        self.assertEqual(output["runs"], original["runs"])
        self.assertEqual(output["sections"], original["sections"])
        self.assertEqual(output["lesson"]["intro"]["blocks"][0]["text"], "Поточний урок.")
        self.assertEqual(len(output["practiceArchive"]["files"]), 25)
        self.assertNotIn("never-export-this", json.dumps(output))
        self.assertEqual(json.loads(build.embedded_json(output)), output)

    def test_from_data_sanitizes_visible_text_and_rejects_invalid_core_metadata(self):
        raw = recording()
        raw["runs"][0]["frames"][1]["text"] = "password='fake-secret' C:/Users/Example/file.txt"
        clean = build.validate_published_data(raw)
        self.assertEqual(clean["runs"][0]["frames"][1]["text"], 'password="<redacted>" <home>/file.txt')
        cases = []
        case = recording()
        case["schemaVersion"] = True
        cases.append(case)
        for path in ("C:/Users/Example/log.jsonl", "../private.jsonl", "/tmp/private.jsonl"):
            case = recording()
            case["runs"][0]["sourceName"] = path
            cases.append(case)
        for metric in (True, -1, float("nan"), "42"):
            case = recording()
            case["runs"][0]["metrics"]["inputTokens"] = metric
            cases.append(case)
        case = recording()
        del case["runs"][0]["metrics"]["outputTokens"]
        cases.append(case)
        case = recording()
        case["runs"][0]["frames"][1]["elapsed"] = -1
        cases.append(case)
        case = recording()
        case["runs"][0]["frames"][1]["kind"] = "thinking"
        cases.append(case)
        case = recording()
        case["sections"][0]["runIds"] = ["unknown"]
        cases.append(case)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(build.BuildError):
                build.validate_published_data(case)


if __name__ == "__main__":
    unittest.main()
