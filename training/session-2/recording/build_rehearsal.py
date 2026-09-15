#!/usr/bin/env python3
"""Import real rehearsal logs, sanitize visible events, and export an offline replay."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PLACEHOLDER = "__REHEARSAL_DATA__"
SESSION_PREFIX = "training/session-2/"
# Deliberately enumerate files: a new file beside the lab is not automatically public.
LAB_FILES = (
    "_acceptance-checks.sql", "_assert-compiled.sql", "_assert-lab.sql", "_guard-owner.sql",
    "_seed.sql", "cleanup.sql", "compile.sql", "install.sql", "reset-starter.sql",
    "settlement-starter.pkb.sql", "settlement.pkb.sql", "settlement.pks.sql", "SPEC.md",
    "verify-baseline.sql", "verify.sql",
)
EXTENSION_FILES = (
    ".claude/settings.json", ".claude/agents/oracle-reviewer.md",
    ".claude/hooks/demo.py", ".claude/hooks/sql_guard.py",
    ".claude/skills/oracle-lab-review/SKILL.md",
    ".claude/skills/oracle-lab-review/references/standards.md",
)
PRACTICE_FILES = tuple(SESSION_PREFIX + name for name in (
    "setup-workspace.py", "check-environment.py", "run-lab.py",
    *("lab/" + name for name in LAB_FILES),
    *("extensions/" + name for name in EXTENSION_FILES),
))
SOURCE_FILES = frozenset(PRACTICE_FILES)
LESSON_SECTION_IDS = frozenset({"baseline", "skill", "agents", "hook", "refactor", "mcp"})


class BuildError(ValueError):
    pass


def number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (integer and value != int(value)):
        return None
    return int(value) if integer else value


def complete_sum(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    values = [number(mapping.get(key), integer=True) for key in keys]
    return sum(values) if all(value is not None for value in values) else None


def visible_text(value):
    """Only visible content; never serialize thinking/signatures or service metadata."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces = [visible_text(item) for item in value]
        return "\n".join(piece for piece in pieces if piece)
    if not isinstance(value, dict):
        return ""
    kind = value.get("type")
    if kind in {"thinking", "redacted_thinking", "image", "signature"}:
        return ""
    if kind == "text":
        return value.get("text", "") if isinstance(value.get("text"), str) else ""
    if kind == "tool_result":
        return visible_text(value.get("content"))
    pieces = []
    for key in ("text", "stdout", "stderr", "content", "result", "output", "summary"):
        piece = visible_text(value.get(key))
        if piece and piece not in pieces:
            pieces.append(piece)
    return "\n".join(pieces)


class Sanitizer:
    PRIVATE_KEY = re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
    )
    TOKEN = re.compile(
        r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]{16,}|"
        r"gh[pousr]_[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16})\b"
    )
    BEARER = re.compile(r"(?i)\bBearer\s+(?!<)[A-Za-z0-9._~+/-]{12,}=*")
    BASIC = re.compile(r"(?i)\bBasic\s+(?!<)[A-Za-z0-9+/]{8,}={0,2}")
    JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b")
    ASSIGNMENT = re.compile(
        r"""(?ix)
        (\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|auth[_-]?token|
             client[_-]?secret|ADB_PASSWORD|ADB_WALLET_B64|wallet[_-]?password)
         ["']?\s*[:=]\s*)
        ("[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}\r\n]+)
        """
    )
    FLAG = re.compile(r"""(?i)(--(?:password|api-key|token|client-secret)\s+)("[^"\r\n]*"|'[^'\r\n]*'|[^\s]+)""")
    ESCAPED_ASSIGNMENT = re.compile(
        r'''(?i)(\b(?:password|passwd|pwd|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|ADB_PASSWORD|ADB_WALLET_B64|wallet[_-]?password)\\"\s*:\s*\\")(.*?)(\\")'''
    )
    ORACLE_LOGIN = re.compile(
        r"""(?i)\b([A-Za-z][A-Za-z0-9_$#]{0,29})/(?:"[^"]*"|[^@\s/'"]+)@([A-Za-z0-9_.-]+)"""
    )
    BASE64 = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{200,}={0,2}(?![A-Za-z0-9+/])")

    def __init__(self, workspaces=(), *, public_code=False):
        self.public_code = public_code
        roots = {str(REPO), *(str(path) for path in workspaces if path)}
        self.workspace_patterns = []
        for root in sorted(roots, key=len, reverse=True):
            parts = re.split(r"[\\/]+", root.rstrip("\\/"))
            self.workspace_patterns.append(re.compile(
                r"[\\/]+".join(re.escape(part) for part in parts) + r"(?:[\\/]+)?", re.I
            ))

    def text(self, value):
        if not isinstance(value, str):
            raise BuildError("Expected a string in visible recording content.")
        # Exact public teaching examples, not real local paths. Keep executable source intact.
        literals = (
            (r"(?m)^#!/usr/bin/env python3(?=\r?$)", "#!/usr/bin/env python3"),
            (r"D:/project(?=\.?(?:\s|$))", "D:/project"),
        ) if self.public_code else ()
        for index, (pattern, _) in enumerate(literals):
            value = re.sub(pattern, f"__PUBLIC_CODE_LITERAL_{index}__", value)
        value = re.sub(r"<system-reminder>.*?</system-reminder>", "", value, flags=re.S)
        value = self.PRIVATE_KEY.sub("<redacted-private-key>", value)
        value = self.TOKEN.sub("<redacted-token>", value)
        value = self.BEARER.sub("Bearer <redacted>", value)
        value = self.BASIC.sub("Basic <redacted>", value)
        value = self.JWT.sub("<redacted-token>", value)
        value = self.ASSIGNMENT.sub(lambda m: m.group(1) + '"<redacted>"', value)
        value = self.ESCAPED_ASSIGNMENT.sub(lambda m: m.group(1) + "<redacted>" + m.group(3), value)
        value = self.FLAG.sub(lambda m: m.group(1) + '"<redacted>"', value)
        value = self.ORACLE_LOGIN.sub(r"\1/<redacted>@\2", value)
        value = re.sub(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@", r"\1<redacted>@", value)
        for pattern in self.workspace_patterns:
            value = pattern.sub("<workspace>/", value)
        value = re.sub(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"'<>]+[\\/]*", "<home>/", value)
        value = re.sub(r"/(?:home|Users)/[^/\s\"'<>]+/?", "<home>/", value)
        value = re.sub(r"(?i)\b[A-Z]:[\\/]+Program Files(?: \(x86\))?[\\/]*", "<tools>/", value)
        value = re.sub(r"(?i)\b[A-Z]:[\\/]+(?:tools|Python\d*)[\\/]*", "<tools>/", value)
        value = re.sub(r"/(?:usr/local/bin|usr/bin|opt)/?", "<tools>/", value)
        value = re.sub(r"/(?:tmp|var/tmp)/", "<temp>/", value)
        # Remaining drive paths are local paths, never public URLs.
        value = re.sub(r"(?i)\b[A-Z]:[\\/]+", "<local-path>/", value)
        self.assert_clean(value)
        for index, (_, literal) in enumerate(literals):
            value = value.replace(f"__PUBLIC_CODE_LITERAL_{index}__", literal)
        return value

    def assert_clean(self, value):
        if any(pattern.search(value) for pattern in (self.PRIVATE_KEY, self.TOKEN, self.BEARER, self.BASIC, self.JWT)):
            raise BuildError("Secret-like content remains after sanitization; export stopped.")
        if self.BASE64.search(value):
            raise BuildError("Unclassified long encoded value in visible content; export stopped.")
        if re.search(r"(?i)\b[A-Z]:[\\/]+|/(?:home|Users)/[^/\s]+/", value):
            raise BuildError("An absolute private path remains after sanitization; export stopped.")

    def tree(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.tree(item) for item in value]
        if isinstance(value, dict):
            return {key: self.tree(item) for key, item in value.items()}
        return value


def read_events(path):
    events, wrapped, previous = [], [], -1
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as error:
        raise BuildError(f"Cannot read Claude source {path.name}.") from error
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError) as error:
            raise BuildError(f"Malformed JSONL in {path.name}, line {line_no}.") from error
        if not isinstance(record, dict):
            raise BuildError(f"JSONL event is not an object in {path.name}, line {line_no}.")
        elapsed = None
        is_wrapped = "event" in record
        if is_wrapped:
            elapsed = number(record.get("elapsed"))
            event = record.get("event")
            if elapsed is None or not isinstance(event, dict) or elapsed < previous:
                raise BuildError(f"Invalid recorded timing in {path.name}, line {line_no}.")
            previous = elapsed
        else:
            event = record
        if event.get("type") in {"recorder_unparsed", "recorder_invalid_event"}:
            raise BuildError(f"Recorder marked invalid stream content in {path.name}, line {line_no}.")
        events.append((event, elapsed))
        wrapped.append(is_wrapped)
    if not events:
        raise BuildError(f"Empty Claude recording: {path.name}.")
    metadata_path = path.with_suffix(".meta.json")
    if metadata_path.is_file():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            raise BuildError(f"Invalid recorder metadata for {path.name}.") from error
        if (not isinstance(metadata, dict) or metadata.get("status") != "success"
                or metadata.get("exitCode") != 0 or isinstance(metadata.get("exitCode"), bool)):
            raise BuildError(f"Recorder metadata marks the process unsuccessful: {path.name}.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if metadata.get("rawSha256") != digest:
            raise BuildError(f"Recorder metadata hash does not match raw stream: {path.name}.")
    recorded = all(wrapped)
    if not recorded:
        events = [(event, None) for event, _ in events]
    return events, recorded


def claude_metrics(result, initial_usage, tool_calls):
    models = result.get("modelUsage")
    if isinstance(models, dict) and models:
        totals = [complete_sum(usage, ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens"))
                  for usage in models.values()]
        outputs = [number(usage.get("outputTokens"), integer=True) if isinstance(usage, dict) else None
                   for usage in models.values()]
        input_tokens = sum(totals) if all(value is not None for value in totals) else None
        output_tokens = sum(outputs) if all(value is not None for value in outputs) else None
    else:
        usage = result.get("usage", {})
        input_tokens = complete_sum(usage, ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        output_tokens = number(usage.get("output_tokens"), integer=True) if isinstance(usage, dict) else None
    duration = number(result.get("duration_ms"))
    return {
        "durationSeconds": duration / 1000 if duration is not None else None,
        "costUsd": number(result.get("total_cost_usd")),
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "toolCalls": tool_calls,
        "initialInputTokens": complete_sum(
            initial_usage, ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
        ),
    }


def parse_claude(path, definition, prompt=""):
    events, recorded = read_events(path)
    terminal = [event for event, _ in events if event.get("type") == "result"]
    if not terminal:
        raise BuildError(f"Claude recording has no terminal result: {path.name}.")
    # Replayed copies are fine; two different terminal results are separate runs.
    unique_results = {json.dumps({k: v for k, v in event.items() if k != "uuid"}, sort_keys=True)
                      for event in terminal}
    if len(unique_results) != 1:
        raise BuildError(f"Claude recording has conflicting terminal results: {path.name}.")
    result = terminal[-1]
    if result.get("subtype") != "success" or result.get("is_error") is not False:
        raise BuildError(f"Claude recording did not complete successfully: {path.name}.")

    inits = [event for event, _ in events if event.get("type") == "system" and event.get("subtype") == "init"]
    sanitizer = Sanitizer(event.get("cwd") for event in inits)
    frames, tool_frames, result_frames, message_frames, seen_hooks = [], {}, {}, {}, set()
    tool_names, assistant_texts, user_texts = {}, set(), set()
    initial_usage, model, version = None, None, None
    for event in inits:
        # Only these two public display values leave init; no tools/profile/config dump.
        if isinstance(event.get("model"), str):
            model = event["model"]
        if isinstance(event.get("claude_code_version"), str):
            version = event["claude_code_version"]

    def emit(kind, text, elapsed=None, **extra):
        frame = {"kind": kind, "text": sanitizer.text(text), **extra}
        if elapsed is not None:
            frame["elapsed"] = elapsed
        frames.append(frame)
        return frame

    if prompt:
        clean_prompt = sanitizer.text(prompt.strip())
        emit("prompt", clean_prompt, 0 if recorded else None)
        user_texts.add(clean_prompt)

    def assistant(text, message_id, elapsed):
        clean = sanitizer.text(text.strip())
        if not clean:
            return
        for frame in message_frames.get(message_id, []):
            if frame["text"] == clean or frame["text"].startswith(clean):
                return
            if clean.startswith(frame["text"]):
                assistant_texts.discard(frame["text"])
                frame["text"] = clean
                assistant_texts.add(clean)
                return
        frame = emit("assistant", clean, elapsed)
        message_frames.setdefault(message_id, []).append(frame)
        assistant_texts.add(clean)

    def tool_result(block, event, elapsed):
        tool_id = block.get("tool_use_id", event.get("tool_use_id", ""))
        text = visible_text(block.get("content"))
        if not text:
            text = visible_text(event.get("tool_use_result", event.get("result")))
        if not text:
            return
        clean = sanitizer.text(text)
        key = (tool_id, clean)
        if key in result_frames:
            return
        frame = emit("result", clean, elapsed, error=block.get("is_error") is True)
        if tool_id in tool_names:
            frame["tool"] = sanitizer.text(tool_names[tool_id])
        result_frames[key] = frame

    for index, (event, elapsed) in enumerate(events):
        kind = event.get("type")
        if kind == "assistant":
            message = event.get("message", {})
            if not isinstance(message, dict):
                raise BuildError(f"Malformed assistant message in {path.name}.")
            if initial_usage is None and not event.get("parent_tool_use_id"):
                initial_usage = message.get("usage", {})
            if not model and isinstance(message.get("model"), str):
                model = message["model"]
            message_id = message.get("id", event.get("uuid", f"event-{index}"))
            content = message.get("content", [])
            if not isinstance(content, list):
                raise BuildError(f"Malformed assistant content in {path.name}.")
            for block_index, block in enumerate(content):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    assistant(visible_text(block), message_id, elapsed)
                elif block.get("type") == "tool_use":
                    name = block.get("name", "Tool")
                    tool_id = block.get("id", f"{message_id}-{block_index}")
                    # Inputs are visible tool arguments, not the raw event envelope.
                    text = sanitizer.text(json.dumps(block.get("input", {}), ensure_ascii=False, indent=2))
                    if tool_id in tool_frames:
                        if len(text) >= len(tool_frames[tool_id]["text"]):
                            tool_frames[tool_id]["text"] = text
                        continue
                    tool_names[tool_id] = name
                    tool_frames[tool_id] = emit("tool", text, elapsed, tool=sanitizer.text(str(name)))
        elif kind == "user":
            message = event.get("message", {})
            content = message.get("content", []) if isinstance(message, dict) else []
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    tool_result(block, event, elapsed)
                elif block.get("type") == "text":
                    text = sanitizer.text(visible_text(block).strip())
                    if text and text not in user_texts:
                        emit("prompt", text, elapsed)
                        user_texts.add(text)
            if not content and event.get("tool_use_result"):
                tool_result(event, event, elapsed)
        elif kind == "tool_result":
            tool_result(event, event, elapsed)
        elif kind == "system" and event.get("subtype") in {"hook_started", "hook_response"}:
            stage = event["subtype"]
            hook_key = (event.get("hook_id", event.get("uuid", index)), stage)
            if hook_key in seen_hooks:
                continue
            seen_hooks.add(hook_key)
            visible = {key: event[key] for key in
                       ("hook_name", "hook_event", "exit_code", "outcome") if key in event}
            visible["stage"] = stage
            text = json.dumps(visible, ensure_ascii=False, indent=2)
            output = visible_text({key: event.get(key) for key in ("stdout", "stderr", "output")})
            if output:
                text += "\n" + output
            emit("hook", text, elapsed, tool=str(event.get("hook_name", "hook")),
                 error=event.get("exit_code") not in (None, 0))
        elif kind == "result":
            text = event.get("result")
            if isinstance(text, str) and text.strip():
                clean = sanitizer.text(text.strip())
                if clean not in assistant_texts:
                    assistant(clean, "terminal-result", elapsed)

    if not any(frame["kind"] != "prompt" for frame in frames):
        raise BuildError(f"Claude recording has no visible response: {path.name}.")
    return {
        **{key: definition.get(key, "") for key in ("id", "title", "subtitle")},
        "kind": "claude", "frames": frames,
        "metrics": claude_metrics(result, initial_usage, len(tool_frames)),
        "model": model, "version": version, "sourceName": path.name,
        "timing": "recorded" if recorded else "paced", "status": "Успішний прогін",
    }


SQL_HEADER = re.compile(r"^LABEL=(\S+)\s+EXIT=(-?\d+)\s+SECONDS=(\d+(?:\.\d+)?)$")
SQL_ERROR = re.compile(r"(?m)^\s*(?:ORA-\d+|SP2-\d+|Error starting\b|ERROR at line\b)")


def parse_sql(path, definition):
    text = path.read_text(encoding="utf-8-sig")
    header, separator, body = text.partition("\n")
    match = SQL_HEADER.fullmatch(header.rstrip("\r"))
    if not separator or not match:
        raise BuildError(f"Missing LABEL/EXIT/SECONDS header in SQL source: {path.name}.")
    command = None
    if body.startswith("COMMAND="):
        command_line, separator, body = body.partition("\n")
        command = command_line[len("COMMAND="):].rstrip("\r")
        if not separator or not command:
            raise BuildError(f"Invalid recorded SQL command in {path.name}.")
        if definition.get("command") and definition["command"] != command:
            raise BuildError(f"Recorded SQL command differs from manifest: {path.name}.")
    actual_exit, duration = int(match[2]), float(match[3])
    expected_exit = definition.get("expectExit", 0)
    marker = definition.get("expectMarker")
    if isinstance(expected_exit, bool) or not isinstance(expected_exit, int):
        raise BuildError(f"Invalid expected SQL exit status: {path.name}.")
    if actual_exit != expected_exit:
        raise BuildError(f"Unexpected SQL exit status in {path.name}: {actual_exit}, expected {expected_exit}.")
    if not isinstance(marker, str) or not marker or marker not in body:
        raise BuildError(f"Missing expected SQL result marker in {path.name}.")
    if actual_exit == 0 and SQL_ERROR.search(body):
        raise BuildError(f"SQL source reports an error despite exit zero: {path.name}.")
    sanitizer = Sanitizer()
    frames = []
    if isinstance(command, str) and command:
        frames.append({"kind": "prompt", "text": sanitizer.text(command)})
    # Preserve exact output after the launcher header, except documented sanitization.
    frames.append({"kind": "result", "text": sanitizer.text(body), "tool": "SQLcl", "error": actual_exit != 0})
    return {
        **{key: definition.get(key, "") for key in ("id", "title", "subtitle")},
        "kind": "sqlcl", "frames": frames,
        "metrics": {"durationSeconds": duration, "costUsd": None, "inputTokens": None,
                    "outputTokens": None, "toolCalls": 0, "initialInputTokens": None},
        "model": None, "version": None, "sourceName": path.name, "timing": "paced",
        "status": "Успішний прогін" if actual_exit == 0 else "Очікувана відмова",
    }


def required_text(mapping, key, *, nonempty=False):
    value = mapping.get(key)
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise BuildError(f"Expected {'nonempty ' if nonempty else ''}text field: {key}.")
    return value


def text_list(value, label):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BuildError(f"Expected a list of text values: {label}.")
    return list(value)


def public_file(path, repo_root=REPO):
    """Resolve an exact allowlist entry; reject aliases through links or junctions."""
    if not isinstance(path, str):
        raise BuildError("Course source path must be text.")
    if path.startswith(("lab/", "extensions/")):
        path = SESSION_PREFIX + path
    if path not in SOURCE_FILES:
        raise BuildError(f"Course source is not on the public allowlist: {path}.")
    root = repo_root.resolve()
    candidate = root
    for part in path.split("/"):
        candidate /= part
        reparse = (candidate.exists() and
                   getattr(candidate.lstat(), "st_file_attributes", 0) &
                   getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if candidate.is_symlink() or reparse:
            raise BuildError("Public course files cannot use symlinks or junctions.")
    if not candidate.resolve().is_relative_to(root) or not candidate.is_file():
        raise BuildError(f"Missing or unsafe public course file: {path}.")
    return path, candidate


def lesson_blocks(blocks, repo_root=REPO, *, depth=0):
    if depth > 12 or not isinstance(blocks, list):
        raise BuildError("Lesson blocks must be an array with at most 12 nesting levels.")
    result = []
    for block in blocks:
        if not isinstance(block, dict):
            raise BuildError("Each lesson block must be an object.")
        kind = block.get("type")
        item = {"type": kind}
        if kind in {"p", "heading"}:
            item["text"] = required_text(block, "text")
        elif kind in {"list", "steps"}:
            item["items"] = text_list(block.get("items"), kind)
        elif kind == "code":
            item.update(language=required_text(block, "language"), text=required_text(block, "text"))
        elif kind == "table":
            headers = text_list(block.get("headers"), "table headers")
            rows = block.get("rows")
            if not headers or not isinstance(rows, list):
                raise BuildError("Lesson tables require headers and rows.")
            checked = [text_list(row, "table row") for row in rows]
            if any(len(row) != len(headers) for row in checked):
                raise BuildError("Lesson table rows must match the header width.")
            item.update(headers=headers, rows=checked)
        elif kind == "callout":
            item.update(title=required_text(block, "title"), text=required_text(block, "text"))
        elif kind == "details":
            item["title"] = required_text(block, "title", nonempty=True)
            if "open" in block:
                if not isinstance(block["open"], bool):
                    raise BuildError("Lesson details.open must be boolean.")
                item["open"] = block["open"]
            item["blocks"] = lesson_blocks(block.get("blocks"), repo_root, depth=depth + 1)
        elif kind == "source":
            canonical, source = public_file(block.get("path"), repo_root)
            item.update(path=canonical, title=required_text(block, "title", nonempty=True),
                        language=required_text(block, "language"), text=source.read_text(encoding="utf-8"))
        elif kind == "link":
            url = required_text(block, "url", nonempty=True)
            parsed = urlsplit(url)
            # Self-contained navigation and explicit public HTTPS references only.
            if not (re.fullmatch(r"#[a-zA-Z0-9_-]+", url) or
                    (parsed.scheme == "https" and parsed.netloc and not parsed.username
                     and not parsed.password and "\\" not in url and not re.search(r"\s", url))):
                raise BuildError("Lesson link must be an anchor or a public HTTPS URL.")
            item.update(text=required_text(block, "text", nonempty=True), url=url)
        else:
            raise BuildError(f"Unknown lesson block type: {kind}.")
        result.append(item)
    return result


def load_lesson(path, repo_root=REPO):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise BuildError("Lesson must be an object.")
    result = {}
    for name in ("intro", "preparation", "closing", "glossary"):
        section = raw.get(name)
        if not isinstance(section, dict):
            raise BuildError(f"Lesson requires {name}.")
        result[name] = {"title": required_text(section, "title", nonempty=True),
                        "blocks": lesson_blocks(section.get("blocks"), repo_root)}
    sections = raw.get("sections")
    if not isinstance(sections, dict) or set(sections) != LESSON_SECTION_IDS:
        raise BuildError("Lesson requires all six named lesson sections.")
    result["sections"] = {}
    for name, section in sections.items():
        if not isinstance(section, dict):
            raise BuildError(f"Invalid lesson section: {name}.")
        result["sections"][name] = {
            key: lesson_blocks(section.get(key), repo_root) for key in ("before", "after")
        }
    return Sanitizer(public_code=True).tree(result)


PRACTICE_START = """# Сесія 2: почати практику

Розпакуйте весь архів у нову теку. Команди нижче виконуйте з кореня цієї теки.
Потрібні Python 3.10+, Git, Oracle SQLcl і Claude Code у PATH.
Для Oracle потрібне підготовлене навчальне підключення SQLcl з назвою train
(власна схема TRAINEE1–TRAINEE5; TRAINER — лише для репетиції тренера).
Доступи налаштовуються окремо; архів їх не містить.

## 1. Перевірити інструменти й створити проєкт

~~~sh
python training/session-2/check-environment.py
python training/session-2/setup-workspace.py
cd training/session-2/workspace
~~~

Створюється окремий Git-репозиторій з початковим комітом, lab/, .claude/ і .mcp.json.
Повторний запуск у ту саму теку зупиниться та збереже вашу роботу.

## 2. Підготувати початковий стан

~~~sh
sql -S -name train @lab/install.sql
sql -S -name train @lab/verify-baseline.sql
claude
~~~

Очікування: BASELINE_CONFIRMED, 13 PASS і 5 KNOWN_FAIL.
Читайте [контракт](training/session-2/lab/SPEC.md) та самодостатню сторінку уроку.
Редагуйте lab/settlement.pkb.sql у створеному workspace.

## 3. Перевірити виправлення

~~~sh
sql -S -name train @lab/compile.sql
sql -S -name train @lab/verify.sql
git diff -- lab/settlement.pkb.sql
~~~

Приймання: ACCEPTANCE_PASS, 18 перевірок, unexpected=0.
Автоматичний запуск з кореня розпакованого архіву:

~~~sh
python training/session-2/run-lab.py compile
python training/session-2/run-lab.py verify
~~~

У початкового пакета verify має завершитися помилкою через п'ять відомих дефектів.
Hook перевіряє Write/Edit SQL-файлів у lab/; він не перевіряє виконання SQL через SQLcl,
Bash або MCP. Текст відповіді моделі не замінює запуск перевірок в Oracle.
"""


def build_practice_archive(repo_root=REPO):
    members = {"START-HERE.md": PRACTICE_START.encode("utf-8")}
    sanitizer = Sanitizer(public_code=True)
    for name in sorted(PRACTICE_FILES):
        canonical, path = public_file(name, repo_root)
        content = path.read_bytes()
        # Fail rather than silently alter executable files or ship private values in the ZIP.
        text = content.decode("utf-8")
        if sanitizer.text(text) != text:
            raise BuildError(f"Private values found in public practice source: {canonical}.")
        members[canonical] = content
    if members[SESSION_PREFIX + "lab/settlement.pkb.sql"] != members[SESSION_PREFIX + "lab/settlement-starter.pkb.sql"]:
        raise BuildError("Practice archive requires the unchanged starter package body.")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[name], compresslevel=9)
    payload = output.getvalue()
    return {"filename": "session-2-practice.zip", "base64": base64.b64encode(payload).decode("ascii"),
            "files": sorted(members), "sha256": hashlib.sha256(payload).hexdigest()}


def attach_lesson_and_practice(data, lesson_path, repo_root=REPO, *, require_lesson=False):
    if lesson_path.is_file():
        data["lesson"] = load_lesson(lesson_path, repo_root)
    elif require_lesson:
        raise BuildError("The explicitly requested lesson file is missing.")
    # Binary content has a known, checked origin; never pass Base64 through the text sanitizer.
    data["practiceArchive"] = build_practice_archive(repo_root)
    return data


def validate_published_data(raw):
    """Retain only typed public recording fields; this does not reverify original raw logs."""
    if not isinstance(raw, dict) or type(raw.get("schemaVersion")) is not int or raw["schemaVersion"] != 1:
        raise BuildError("Published data must use schemaVersion 1.")
    data = {"schemaVersion": 1}
    for key in ("title", "date", "description"):
        data[key] = required_text(raw, key)
    data["method"] = text_list(raw.get("method"), "method")
    if not isinstance(raw.get("runs"), list) or not raw["runs"]:
        raise BuildError("Published data requires runs.")
    ids, runs = set(), []
    for raw_run in raw["runs"]:
        if not isinstance(raw_run, dict):
            raise BuildError("Invalid published run.")
        run = {key: required_text(raw_run, key) for key in
               ("id", "title", "subtitle", "kind", "sourceName", "timing", "status")}
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", run["id"]) or run["id"] in ids:
            raise BuildError("Published run ids must be unique safe identifiers.")
        ids.add(run["id"])
        if run["kind"] not in {"claude", "sqlcl"} or run["timing"] not in {"recorded", "paced"}:
            raise BuildError("Invalid run kind or timing.")
        if run["status"] not in {"Успішний прогін", "Очікувана відмова"}:
            raise BuildError("Invalid published run status.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", run["sourceName"]) or run["sourceName"] in {".", ".."}:
            raise BuildError("Published sourceName must be a filename without a path.")
        for key in ("model", "version"):
            value = raw_run.get(key)
            if value is not None and not isinstance(value, str):
                raise BuildError(f"Invalid published run {key}.")
            run[key] = value
        metrics = raw_run.get("metrics")
        if not isinstance(metrics, dict):
            raise BuildError("Published run requires metrics.")
        run["metrics"] = {}
        for key in ("durationSeconds", "costUsd", "inputTokens", "outputTokens", "toolCalls", "initialInputTokens"):
            if key not in metrics:
                raise BuildError(f"Missing published metric: {key}.")
            value = metrics[key]
            if ((value is None and key == "toolCalls") or
                    (value is not None and number(value, integer=key.endswith("Tokens") or key == "toolCalls") is None)):
                raise BuildError(f"Invalid published metric: {key}.")
            run["metrics"][key] = value
        if not isinstance(raw_run.get("frames"), list) or not raw_run["frames"]:
            raise BuildError("Published run requires frames.")
        run["frames"] = []
        previous_elapsed = -1
        for raw_frame in raw_run["frames"]:
            if not isinstance(raw_frame, dict):
                raise BuildError("Invalid published frame.")
            frame = {key: required_text(raw_frame, key) for key in ("kind", "text")}
            if frame["kind"] not in {"prompt", "tool", "result", "assistant", "hook"}:
                raise BuildError("Invalid published frame kind.")
            if "tool" in raw_frame:
                frame["tool"] = required_text(raw_frame, "tool")
            if "error" in raw_frame:
                if not isinstance(raw_frame["error"], bool):
                    raise BuildError("Published frame error must be boolean.")
                frame["error"] = raw_frame["error"]
            if "elapsed" in raw_frame:
                elapsed = number(raw_frame["elapsed"])
                if elapsed is None or elapsed < previous_elapsed or run["timing"] != "recorded":
                    raise BuildError("Invalid published frame timing.")
                previous_elapsed = elapsed
                frame["elapsed"] = elapsed
            elif run["timing"] == "recorded":
                raise BuildError("Recorded frames require elapsed times.")
            run["frames"].append(frame)
        runs.append(run)
    sections, section_ids = [], set()
    if not isinstance(raw.get("sections"), list):
        raise BuildError("Published data requires sections.")
    for raw_section in raw["sections"]:
        if not isinstance(raw_section, dict):
            raise BuildError("Invalid published section.")
        section = {key: required_text(raw_section, key) for key in
                   ("id", "title", "slot", "goal", "takeaway")}
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", section["id"]) or section["id"] in section_ids:
            raise BuildError("Published section ids must be unique safe identifiers.")
        section_ids.add(section["id"])
        section["runIds"] = text_list(raw_section.get("runIds"), "section runIds")
        if not set(section["runIds"]).issubset(ids):
            raise BuildError("Published section refers to an unknown run.")
        sections.append(section)
    data.update(runs=runs, sections=sections)
    return Sanitizer().tree(data)


def build_from_data(path, lesson_path=None, *, repo_root=REPO):
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    data = validate_published_data(raw)
    return attach_lesson_and_practice(data, lesson_path or HERE / "lesson.json", repo_root,
                                     require_lesson=lesson_path is not None)


def build_data(manifest_path, lesson_path=None, *, repo_root=REPO):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise BuildError("Manifest must use schemaVersion 1.")
    definitions, sections = manifest.get("runs"), manifest.get("sections")
    if not isinstance(definitions, list) or not definitions or not isinstance(sections, list):
        raise BuildError("Manifest requires runs and sections.")
    ids, runs = set(), []
    for definition in definitions:
        if not isinstance(definition, dict) or not isinstance(definition.get("id"), str):
            raise BuildError("Each run requires a string id.")
        if definition["id"] in ids:
            raise BuildError("Duplicate run id in manifest.")
        ids.add(definition["id"])
        source = definition.get("source")
        if not isinstance(source, str):
            raise BuildError("Each run requires a source path.")
        path = (manifest_path.parent / source).resolve()
        prompt = definition.get("prompt", "")
        if definition.get("promptFile"):
            prompt = (manifest_path.parent / definition["promptFile"]).read_text(encoding="utf-8-sig")
        if definition.get("kind") == "claude":
            runs.append(parse_claude(path, definition, prompt))
        elif definition.get("kind") == "sqlcl":
            runs.append(parse_sql(path, definition))
        else:
            raise BuildError("Run kind must be claude or sqlcl.")
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("runIds"), list):
            raise BuildError("Each section requires runIds.")
        if not set(section["runIds"]).issubset(ids):
            raise BuildError("Section refers to an unknown run.")
    data = {key: manifest.get(key, "" if key != "method" else []) for key in
            ("schemaVersion", "title", "date", "description", "method")}
    data["sections"] = sections
    data["runs"] = runs
    return attach_lesson_and_practice(Sanitizer().tree(data),
                                     lesson_path or manifest_path.parent / "lesson.json",
                                     repo_root, require_lesson=lesson_path is not None)


def embedded_json(data):
    value = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (value.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render_html(template, data):
    if template.count(PLACEHOLDER) != 1:
        raise BuildError("HTML template must contain exactly one __REHEARSAL_DATA__ placeholder.")
    return template.replace(PLACEHOLDER, embedded_json(data))


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", delete=False,
                                         dir=path.parent, prefix=path.name + ".", suffix=".tmp") as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=HERE / "sources.json")
    parser.add_argument("--from-data", type=Path,
                        help="Reuse sanitized published runs; original raw-log provenance is not revalidated.")
    parser.add_argument("--lesson", type=Path, help="Lesson JSON; otherwise load lesson.json when available.")
    parser.add_argument("--template", type=Path, default=HERE / "rehearsal.template.html")
    parser.add_argument("--html", type=Path, default=REPO / "tools/session-2-rehearsal.html")
    parser.add_argument("--data", type=Path, default=REPO / "tools/session-2-rehearsal-data.json")
    args = parser.parse_args()
    try:
        data = (build_from_data(args.from_data.resolve(), args.lesson) if args.from_data
                else build_data(args.manifest.resolve(), args.lesson))
        html = render_html(args.template.read_text(encoding="utf-8"), data)
        plain = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        atomic_write(args.data.resolve(), plain)
        atomic_write(args.html.resolve(), html)
    except (BuildError, OSError, ValueError, TypeError) as error:
        print(f"REHEARSAL_BUILD_FAIL: {error}", file=sys.stderr)
        return 1
    print(f"REHEARSAL_READY: {len(data['runs'])} runs, {len(data['sections'])} sections")
    if args.from_data:
        print("PUBLISHED_DATA_REUSED: raw-log provenance was not revalidated.")
    for run in data["runs"]:
        print(f"{run['id']}: {len(run['frames'])} frames, {run['metrics']['toolCalls']} tool calls, {run['timing']}")
    print(args.html.resolve())
    print(args.data.resolve())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
