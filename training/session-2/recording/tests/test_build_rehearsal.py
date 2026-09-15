"""Focused importer/exporter tests using synthetic public fixtures; no Claude or Oracle calls."""

import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "build_rehearsal.py"
spec = importlib.util.spec_from_file_location("session2_build_rehearsal", SCRIPT)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def terminal(**extra):
    return {"type": "result", "subtype": "success", "is_error": False, "result": "Готово.", **extra}


def assistant(message_id, content, **extra):
    return {"type": "assistant", "parent_tool_use_id": None,
            "message": {"id": message_id, "content": content, **extra}}


class RehearsalImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="session2-recording-test-")
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.addCleanup(self.temp.cleanup)
        self.definition = {"id": "example", "title": "Приклад", "subtitle": "", "kind": "claude"}

    def source(self, events):
        path = self.root / "run.jsonl"
        path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events),
                        encoding="utf-8")
        return path

    def test_requires_well_formed_successful_terminal_result(self):
        cases = [
            [],
            [{"type": "assistant", "message": {"id": "m", "content": []}}],
            [terminal(subtype="error_max_turns", is_error=True)],
            [terminal(is_error=True)],
            [terminal(), terminal(result="Інший прогін.")],
            [["not", "an", "event"]],
            [{"type": "recorder_unparsed", "text": "invalid stream line"}, terminal()],
            [{"type": "recorder_invalid_event", "value": []}, terminal()],
        ]
        for events in cases:
            with self.subTest(events=events):
                with self.assertRaises(build.BuildError):
                    build.parse_claude(self.source(events), self.definition)
        invalid = self.root / "bad.jsonl"
        invalid.write_text('{"type":', encoding="utf-8")
        with self.assertRaises(build.BuildError):
            build.parse_claude(invalid, self.definition)

    def test_adjacent_recorder_metadata_must_confirm_success_and_raw_hash(self):
        path = self.source([terminal()])
        metadata_path = path.with_suffix(".meta.json")
        good = {"status": "success", "exitCode": 0,
                "rawSha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        metadata_path.write_text(json.dumps(good), encoding="utf-8")
        self.assertEqual(build.parse_claude(path, self.definition)["status"], "Успішний прогін")
        for changed in [dict(good, status="failed"), dict(good, exitCode=1),
                        dict(good, exitCode=False), dict(good, rawSha256="invalid")]:
            with self.subTest(changed=changed):
                metadata_path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(build.BuildError):
                    build.parse_claude(path, self.definition)

    def test_dedup_preserves_distinct_tools_fragments_and_subagent_result(self):
        read = {"type": "tool_use", "id": "tool-read", "name": "Read", "input": {"file_path": "lab/SPEC.md"}}
        task = {"type": "tool_use", "id": "tool-agent", "name": "Agent", "input": {"prompt": "Перевір контракт."}}
        result = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tool-agent", "content": [
                {"type": "text", "text": "Висновок підлеглого агента."},
                {"type": "text", "text": "Перевірити NULL."},
            ]}
        ]}}
        events = [
            assistant("m1", [{"type": "text", "text": "Читаю."}]),
            assistant("m1", [{"type": "text", "text": "Читаю."}, read]),
            assistant("m1", [read, task]),
            result, result,
            assistant("m2", [{"type": "text", "text": "Готово."}]),
            terminal(),
        ]
        run = build.parse_claude(self.source(events), self.definition, prompt="Зроби рев'ю.")
        self.assertEqual(run["metrics"]["toolCalls"], 2)
        self.assertEqual(sum(frame["kind"] == "tool" for frame in run["frames"]), 2)
        self.assertEqual(sum(frame["kind"] == "result" for frame in run["frames"]), 1)
        self.assertEqual(sum(frame["text"] == "Готово." for frame in run["frames"]), 1)
        self.assertIn("Висновок підлеглого агента.\nПеревірити NULL.",
                      [frame["text"] for frame in run["frames"]])

    def test_cumulative_assistant_text_and_tool_input_replace_partial_frames(self):
        events = [
            assistant("m1", [{"type": "text", "text": "Читаю"}]),
            assistant("m1", [{"type": "text", "text": "Читаю контракт."}]),
            assistant("m1", [{"type": "tool_use", "id": "t", "name": "Read", "input": {}}]),
            assistant("m1", [{"type": "tool_use", "id": "t", "name": "Read",
                              "input": {"file_path": "lab/SPEC.md"}}]),
            terminal(),
        ]
        run = build.parse_claude(self.source(events), self.definition)
        self.assertEqual([frame["text"] for frame in run["frames"] if frame["kind"] == "assistant"],
                         ["Читаю контракт.", "Готово."])
        self.assertEqual(run["metrics"]["toolCalls"], 1)
        self.assertIn("lab/SPEC.md", next(frame["text"] for frame in run["frames"] if frame["kind"] == "tool"))

    def test_skips_thinking_signatures_and_private_init_profile(self):
        events = [
            {"type": "system", "subtype": "init", "model": "test-model", "claude_code_version": "2.1.0",
             "cwd": "D:/private/project/workspace", "apiKeySource": "PRIVATE_PROFILE_SENTINEL",
             "mcp_servers": [{"name": "PRIVATE_ACCOUNT_SENTINEL"}]},
            assistant("m1", [{"type": "thinking", "thinking": "PRIVATE_THOUGHT_SENTINEL",
                               "signature": "PRIVATE_SIGNATURE_SENTINEL"}]),
            terminal(result="D:/private/project/workspace/lab/SPEC.md"),
        ]
        run = build.parse_claude(self.source(events), self.definition)
        serialized = json.dumps(run)
        for private in ("PRIVATE_PROFILE_SENTINEL", "PRIVATE_ACCOUNT_SENTINEL",
                        "PRIVATE_THOUGHT_SENTINEL", "PRIVATE_SIGNATURE_SENTINEL", "D:/private"):
            self.assertNotIn(private, serialized)
        self.assertEqual(run["model"], "test-model")
        self.assertEqual(run["version"], "2.1.0")
        self.assertEqual(run["frames"][0]["text"], "<workspace>/lab/SPEC.md")

    def test_real_hook_response_is_preserved_and_deduplicated(self):
        event = {"type": "system", "subtype": "hook_response", "hook_id": "h1",
                 "hook_name": "PreToolUse:Write", "hook_event": "PreToolUse",
                 "exit_code": 2, "outcome": "blocked",
                 "stderr": "SQL guard: заблоковано.", "output": "SQL guard: заблоковано."}
        run = build.parse_claude(self.source([event, event, terminal()]), self.definition)
        hooks = [frame for frame in run["frames"] if frame["kind"] == "hook"]
        self.assertEqual(len(hooks), 1)
        self.assertTrue(hooks[0]["error"])
        self.assertEqual(hooks[0]["text"].count("SQL guard: заблоковано."), 1)

    def test_external_tool_result_without_user_envelope_is_supported(self):
        event = {"type": "tool_result", "tool_use_id": "agent-task",
                 "result": {"content": [{"type": "text", "text": "Зовнішній висновок агента."}]}}
        run = build.parse_claude(self.source([event, terminal()]), self.definition)
        self.assertIn("Зовнішній висновок агента.", [frame["text"] for frame in run["frames"]])

    def test_metrics_use_all_models_caches_and_first_root_usage(self):
        child = assistant("child", [{"type": "text", "text": "Підлеглий."}],
                          usage={"input_tokens": 900, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})
        child["parent_tool_use_id"] = "parent-tool"
        root = assistant("root", [{"type": "text", "text": "Готово."}],
                         usage={"input_tokens": 2, "cache_creation_input_tokens": 3, "cache_read_input_tokens": 5})
        end = terminal(duration_ms=1250, total_cost_usd=0, modelUsage={
            "one": {"inputTokens": 2, "cacheCreationInputTokens": 3, "cacheReadInputTokens": 5, "outputTokens": 7},
            "two": {"inputTokens": 11, "cacheCreationInputTokens": 13, "cacheReadInputTokens": 17, "outputTokens": 19},
        })
        metrics = build.parse_claude(self.source([child, root, end]), self.definition)["metrics"]
        self.assertEqual(metrics["inputTokens"], 51)
        self.assertEqual(metrics["outputTokens"], 26)
        self.assertEqual(metrics["initialInputTokens"], 10)
        self.assertEqual(metrics["durationSeconds"], 1.25)
        self.assertEqual(metrics["costUsd"], 0)

    def test_missing_metrics_stay_null_and_explicit_zero_stays_zero(self):
        missing = build.parse_claude(self.source([terminal()]), self.definition)["metrics"]
        for key in ("inputTokens", "outputTokens", "initialInputTokens", "durationSeconds", "costUsd"):
            self.assertIsNone(missing[key], key)
        self.assertEqual(missing["toolCalls"], 0)
        partial = terminal(modelUsage={"one": {"inputTokens": 2, "outputTokens": 0}})
        metrics = build.parse_claude(self.source([partial]), self.definition)["metrics"]
        self.assertIsNone(metrics["inputTokens"], "Missing cache measurements cannot mean zero.")
        self.assertEqual(metrics["outputTokens"], 0)

    def test_only_complete_elapsed_wrappers_are_recorded(self):
        raw = [assistant("m", [{"type": "text", "text": "Готово."}]), terminal()]
        wrapped = [{"elapsed": 0.5, "event": raw[0]}, {"elapsed": 1.2, "event": raw[1]}]
        run = build.parse_claude(self.source(wrapped), self.definition, prompt="Запит.")
        self.assertEqual(run["timing"], "recorded")
        self.assertEqual(run["frames"][0]["elapsed"], 0)
        self.assertEqual(run["frames"][1]["elapsed"], 0.5)
        mixed = build.parse_claude(self.source([wrapped[0], raw[1]]), self.definition)
        self.assertEqual(mixed["timing"], "paced")
        self.assertFalse(any("elapsed" in frame for frame in mixed["frames"]))
        for bad in [[{"elapsed": -1, "event": raw[0]}, wrapped[1]],
                    [wrapped[1], {"elapsed": 0.5, "event": raw[0]}]]:
            with self.subTest(bad=bad):
                with self.assertRaises(build.BuildError):
                    build.parse_claude(self.source(bad), self.definition)

    def test_paths_and_credentials_are_redacted_and_unknown_encoded_values_fail(self):
        clean = build.Sanitizer(["D:/bank/workspace"]).text(
            'D:\\bank\\workspace\\lab\\file.sql C:/Users/person/.claude/file '
            '/home/person/project C:/Python314/python.exe '
            'password="FakeValue123" ADB_PASSWORD=FakeOther123 '
            'TRAINER/FakeOracle123@training_low '
            'Bearer abcdefghijklmnopqrstuvwxyz '
            'sk-ant-abcdefghijklmnopqrstuvwxyz123456'
        )
        for secret in ("FakeValue123", "FakeOther123", "FakeOracle123",
                       "abcdefghijklmnopqrstuvwxyz", "C:/Users/person", "/home/person", "D:\\bank"):
            self.assertNotIn(secret, clean)
        self.assertIn("<workspace>/", clean)
        self.assertIn("<home>/", clean)
        self.assertIn("<tools>/", clean)
        with self.assertRaises(build.BuildError):
            build.Sanitizer().text("unclassified=" + "A" * 240)
        escaped = build.Sanitizer().text(r'{\"password\": \"FakeNestedValue123\"}')
        self.assertNotIn("FakeNestedValue123", escaped)
        self.assertNotIn("dXNlcjpwYXNzd29yZA==",
                         build.Sanitizer().text("Authorization: Basic dXNlcjpwYXNzd29yZA=="))
        self.assertNotIn("FakeGenericPass123",
                         build.Sanitizer().text("CUSTOMUSER/FakeGenericPass123@training_low"))

    def test_json_embedding_cannot_close_script_tag_or_change_payload(self):
        payload = {"text": '</script><script>alert("x")</script>&\u2028\u2029'}
        embedded = build.embedded_json(payload)
        self.assertNotIn("<", embedded)
        self.assertNotIn("&", embedded)
        self.assertEqual(json.loads(embedded), payload)
        template = '<script type="application/json">__REHEARSAL_DATA__</script>'
        rendered = build.render_html(template, payload)
        self.assertEqual(rendered.count("</script>"), 1)
        for bad in ("no placeholder", "__REHEARSAL_DATA____REHEARSAL_DATA__"):
            with self.assertRaises(build.BuildError):
                build.render_html(bad, payload)

    def test_sql_expected_before_and_after_results_preserve_actual_output(self):
        path = self.root / "sql.txt"
        command = "python run-lab.py verify"
        before = "\nORA-20999: VERIFY_FAIL unexpected=5\n"
        path.write_text("LABEL=before EXIT=1 SECONDS=7.25\nCOMMAND=" + command + "\n" + before, encoding="utf-8")
        definition = {**self.definition, "kind": "sqlcl", "command": command,
                      "expectExit": 1, "expectMarker": "unexpected=5"}
        run = build.parse_sql(path, definition)
        self.assertEqual(run["status"], "Очікувана відмова")
        self.assertEqual(run["frames"][0]["text"], command)
        self.assertEqual(run["frames"][1]["text"], before)
        self.assertTrue(run["frames"][1]["error"])
        self.assertEqual(run["metrics"]["durationSeconds"], 7.25)
        self.assertIsNone(run["metrics"]["costUsd"])
        after = "[PASS] contract\nACCEPTANCE_PASS: checks=18, unexpected=0\n"
        path.write_text("LABEL=after EXIT=0 SECONDS=8.5\nCOMMAND=" + command + "\n" + after, encoding="utf-8")
        definition.update(expectExit=0, expectMarker="ACCEPTANCE_PASS: checks=18, unexpected=0")
        success = build.parse_sql(path, definition)
        self.assertEqual(success["status"], "Успішний прогін")
        self.assertEqual(success["frames"][1]["text"], after)

    def test_sql_incomplete_failed_or_mismatched_sources_cannot_export_success(self):
        path = self.root / "sql.txt"
        definition = {**self.definition, "kind": "sqlcl", "expectExit": 0, "expectMarker": "PASS"}
        for raw in ["PASS", "LABEL=test EXIT=1 SECONDS=1\nPASS\n",
                    "LABEL=test EXIT=0 SECONDS=1\nno marker\n",
                    "LABEL=test EXIT=0 SECONDS=1\nPASS\n ORA-20999: failed\n"]:
            with self.subTest(raw=raw):
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(build.BuildError):
                    build.parse_sql(path, definition)
        path.write_text("LABEL=test EXIT=0 SECONDS=1\nCOMMAND=actual command\nPASS\n", encoding="utf-8")
        with self.assertRaises(build.BuildError):
            build.parse_sql(path, {**definition, "command": "invented command"})
        path.write_text("LABEL=test EXIT=0 SECONDS=1\nPASS\n", encoding="utf-8")
        run = build.parse_sql(path, {**definition, "command": "not actually recorded"})
        self.assertEqual([frame["kind"] for frame in run["frames"]], ["result"])


if __name__ == "__main__":
    unittest.main()
