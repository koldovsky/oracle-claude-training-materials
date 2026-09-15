#!/usr/bin/env python3
"""Навчальний PreToolUse hook: перевірка запропонованих Write/Edit у lab/*.sql.

Це демонстрація, не SQL-парсер і не межа безпеки. Скрипт не змінює файлів.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys


MAX_PAYLOAD_BYTES = 2_000_000
DESTRUCTIVE = re.compile(
    r"\b(?:DROP|TRUNCATE)\b|"
    r"\bALTER(?:\s|/\*.*?\*/|--[^\r\n]*(?:\r?\n|$))+SYSTEM\b",
    re.IGNORECASE | re.DOTALL,
)


class GuardError(ValueError):
    """Запит неможливо надійно перевірити в межах демонстрації."""


def string_field(data: dict, name: str, *, nonempty: bool = False) -> str:
    value = data.get(name)
    if not isinstance(value, str) or (nonempty and not value.strip()):
        raise GuardError(f"поле {name} має бути {'непорожнім ' if nonempty else ''}рядком")
    if "\x00" in value:
        raise GuardError(f"поле {name} містить NUL")
    return value


def native_path(value: str) -> Path:
    # Git Bash може передати корінь як /d/project, Windows Python очікує D:/project.
    if os.name == "nt" and re.match(r"^/[A-Za-z]/", value):
        value = value[1].upper() + ":/" + value[3:]
    result = Path(value)
    if not result.is_absolute():
        raise GuardError("очікувався абсолютний шлях")
    return result.resolve()


def check_payload(payload: object, project_dir: str | None) -> None:
    if not isinstance(payload, dict):
        raise GuardError("вхід має бути JSON-об'єктом")
    if payload.get("hook_event_name") != "PreToolUse":
        raise GuardError("очікувалася подія PreToolUse")
    tool_name = string_field(payload, "tool_name", nonempty=True)
    if tool_name not in {"Write", "Edit"}:
        return
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise GuardError("tool_input має бути JSON-об'єктом")
    file_path = string_field(tool_input, "file_path", nonempty=True)
    if tool_name == "Write":
        proposed = string_field(tool_input, "content")
    else:
        old_string = string_field(tool_input, "old_string", nonempty=True)
        new_string = string_field(tool_input, "new_string")
        replace_all = tool_input.get("replace_all", False)
        if not isinstance(replace_all, bool):
            raise GuardError("replace_all має бути boolean")
    if not isinstance(project_dir, str) or not project_dir.strip():
        raise GuardError("не задано CLAUDE_PROJECT_DIR")
    project_root = native_path(project_dir)
    target = native_path(file_path)
    lab_root = (project_root / "lab").resolve()
    if target.suffix.lower() != ".sql" or not target.is_relative_to(lab_root):
        return

    if tool_name == "Edit":
        # Відтворюємо результат цілого файлу, не лише вставлений фрагмент.
        with target.open("r", encoding="utf-8-sig", newline="") as source:
            current = source.read()
        occurrences = current.count(old_string)
        if occurrences == 0:
            raise GuardError("old_string не знайдено; перечитай SQL-файл")
        if occurrences != 1 and not replace_all:
            raise GuardError("old_string неоднозначний; уточни заміну")
        proposed = current.replace(old_string, new_string, -1 if replace_all else 1)

    # Ловимо також просту конкатенацію літералів: 'DR' || 'OP TABLE ...'.
    # Коментарі/літерали навмисно не виключаємо: можливі хибні блокування.
    inspected = re.sub(r"'\s*\|\|\s*'", "", proposed)
    if DESTRUCTIVE.search(inspected):
        raise GuardError(
            "у запропонованому SQL-файлі знайдено DROP, TRUNCATE або ALTER SYSTEM; "
            "ця навчальна зміна заблокована. Не обходь hook іншим інструментом"
        )


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise GuardError("завеликий JSON-запит для навчальної перевірки")
        payload = json.loads(raw.decode("utf-8-sig"))
        check_payload(payload, os.environ.get("CLAUDE_PROJECT_DIR"))
    except (GuardError, json.JSONDecodeError, UnicodeError, OSError) as error:
        print(f"SQL guard: заблоковано — {error}.", file=sys.stderr)
        return 2
    except Exception:
        # Exit 1 не блокує PreToolUse. Не допускаємо випадкового дозволу при збої.
        print("SQL guard: заблоковано — внутрішня помилка перевірки.", file=sys.stderr)
        return 2
    # Жодного permissionDecision=allow: звичайні дозволи Claude Code лишаються.
    return 0


if __name__ == "__main__":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
