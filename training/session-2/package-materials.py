#!/usr/bin/env python3
"""Build and verify the Session 2 participant ZIP from an explicit allowlist."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile


SESSION = Path(__file__).resolve().parent
REPO = SESSION.parents[1]
DEFAULT_OUTPUT = REPO / "tools/session-2-participant.zip"

REQUIRED_FILES = (
    "training/HANDOUT-SESSION-2.md",
    "training/HOMEWORK-SESSION-2.md",
    "training/session-2/README.md",
    "training/session-2/setup-workspace.py",
    "training/session-2/check-environment.py",
    "training/session-2/run-lab.py",
    "tools/cheatsheet-session-2.html",
    "tools/session-2-rehearsal.html",
    "tools/session-2.html",
    "tools/session-2-slides.html",
    "slides/session-2.pdf",
    "tools/session-2-slides/manifest.json",
) + tuple(f"tools/session-2-slides/slide-{i:02d}.png" for i in range(1, 27))
ALLOWED_TREES = {
    "training/session-2/lab": {".sql", ".md"},
    "training/session-2/extensions": {".py", ".md", ".json"},
    "training/session-2/tests": {".py"},
}
FORBIDDEN_PARTS = {
    "trainer", "rehearsal", ".rehearsal", ".git", "__pycache__", "node_modules",
    ".wallet", "adb-wallet", ".secrets", "restored",
}
FORBIDDEN_NAMES = {
    "settings.local.json", "settlement-reference.pkb.sql", "apply-reference.sql",
    "expected-findings.md", "credentials.txt", "pass.txt",
}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".log", ".gpg", ".p12", ".sso", ".pem", ".jks", ".b64"}

START_HERE = """# Сесія 2 · почніть тут

Розпакуйте весь архів зі збереженням структури тек. Наведені перші команди
виконуйте з теки, де лежить цей START-HERE.md.

Відкрийте [START-HERE.html](START-HERE.html) або
[центр матеріалів](tools/session-2.html) у браузері: звідти можна перейти
до слайдів, демо, шпаргалки та двогодинного відеоуроку онлайн.

## Матеріали

- [Робочий листок](training/HANDOUT-SESSION-2.md)
- [Домашнє завдання №2](training/HOMEWORK-SESSION-2.md)
- [Інструкція лабораторії](training/session-2/README.md)
- [Контракт пакета](training/session-2/lab/SPEC.md)
- [Шпаргалка з командами](tools/cheatsheet-session-2.html)
- [Записи демонстрацій](tools/session-2-rehearsal.html)
- [Слайди PDF](slides/session-2.pdf)
- [Слайди з навігацією](tools/session-2-slides.html)
- [Відеоурок · 2 години · онлайн](https://koldovsky.github.io/claude-code-oracle-training/session-2-video.html)

Записи містять розбір і виправлення пакета. Відкривайте відповідний фрагмент
після власної спроби виконати вправу. Програвач працює офлайн.

## Підготовка

Потрібні Python 3.10+, Git, SQLcl, Claude Code та ваше збережене підключення
SQLcl train із Сесії 1. Доступ до навчальної Oracle надає тренер окремо.
Якщо Python у вашій системі запускається як python3, використовуйте цю назву.

    python training/session-2/check-environment.py
    python training/session-2/check-environment.py --database
    python training/session-2/setup-workspace.py
    cd training/session-2/workspace

Очікуємо PREFLIGHT_PASS та WORKSPACE_READY. Підготовка створює окремий Git-проєкт
із початковим комітом. Якщо робоча тека вже існує, вона не перезаписується.

## Початок заняття

Наступні команди виконуйте з підготовленої робочої теки:

    sql -S -name train @lab/install.sql
    sql -S -name train @lab/verify-baseline.sql
    claude

Кожен SQL-скрипт завершує свій процес SQLcl. Використовуйте окремі навчальні
підключення без іншої незавершеної транзакції.

BASELINE_CONFIRMED підтверджує початковий пакет із п'ятьма відомими дефектами.
Після виправлення lab/settlement.pkb.sql:

    sql -S -name train @lab/compile.sql
    sql -S -name train @lab/verify.sql

Очікуємо COMPILE_OK та ACCEPTANCE_PASS: усі 18 перевірок пройдено.
Специфікацію, перевірки й settlement-starter.pkb.sql залишаємо незміненими.
Повернення до початку та очищення описані в інструкції лабораторії.

## Необов'язково: запуск через Python

Для автоматизованого термінала або запуску з перевіркою результату можна
використати run-lab.py. З теки START-HERE.md:

    python training/session-2/run-lab.py compile
    python training/session-2/run-lab.py verify

За замовчуванням він використовує підготовлену теку training/session-2/workspace
та з'єднання train. Для іншої теки або з'єднання:

    python training/session-2/run-lab.py verify --workspace "шлях/до/робочої теки" --connection train

Очікуємо SQLCL_RUN_PASS. Скрипт перевіряє код завершення SQLcl, повідомлення
про помилки та підсумкову позначку обраної дії. Доступні дії install, baseline,
compile, verify, reset і cleanup; вибирайте лише потрібну дію.

Для локальної перевірки інструментів архіву, з теки START-HERE.md:

    python -m unittest discover -s training/session-2/tests -v

Ці Python-тести не підключаються до бази даних.
"""

START_HERE_HTML = """<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сесія 2 · почніть тут</title><style>body{font:19px/1.7 system-ui;background:#090e15;color:#e8f0f5;max-width:760px;margin:8vh auto;padding:24px}a{color:#62dbd5}h1{line-height:1.2}.button{display:inline-block;padding:12px 20px;background:#62dbd5;color:#08252c;border-radius:8px;font-weight:bold;text-decoration:none}li{margin:12px 0}code{font-size:.9em}</style></head><body>
<h1>Сесія 2 · почніть тут</h1>
<p>Розпакуйте весь архів зі збереженням структури тек. У центрі матеріалів є всі переходи, пояснення та команди підготовки.</p>
<p><a class="button" href="tools/session-2.html">Відкрити центр матеріалів</a></p>
<ul><li><a href="tools/session-2-slides.html">Слайди</a></li><li><a href="tools/session-2-rehearsal.html">Демо з поясненнями</a></li><li><a href="tools/cheatsheet-session-2.html">Шпаргалка</a></li><li><a href="https://koldovsky.github.io/claude-code-oracle-training/session-2-video.html">Відеоурок · 2 години · онлайн</a></li><li><a href="START-HERE.md">Докладна текстова інструкція</a></li></ul>
<p>Перші команди виконуйте з цієї теки, де лежить <code>START-HERE.html</code>. Файли лабораторії, PDF і текстовий урок доступні офлайн. Відеоурок завантажується окремо зі своєї сторінки.</p>
</body></html>
"""


def forbidden(name: str) -> bool:
    path = PurePosixPath(name)
    parts = tuple(part.lower() for part in path.parts)
    return (
        path.is_absolute() or ".." in parts or "\\" in name
        or any(part in FORBIDDEN_PARTS or part.startswith("workspace") for part in parts)
        or path.name.lower() in FORBIDDEN_NAMES
        or path.name.lower().startswith(".env")
        or any(token in path.name.lower() for token in ("credential", "wallet", "secret"))
        or path.suffix.lower() in FORBIDDEN_SUFFIXES
    )


def collect_files() -> dict[str, Path]:
    files = {}
    for name in REQUIRED_FILES:
        source = REPO / name
        if not source.is_file():
            raise RuntimeError(f"Required final material is missing: {name}")
        files[name] = source
    for prefix, suffixes in ALLOWED_TREES.items():
        directory = REPO / prefix
        if not directory.is_dir():
            raise RuntimeError(f"Required participant directory is missing: {prefix}")
        for source in directory.rglob("*"):
            name = source.relative_to(REPO).as_posix()
            if source.is_file() and source.suffix.lower() in suffixes and not forbidden(name):
                files[name] = source
    for name, source in files.items():
        if forbidden(name) or source.is_symlink() or not source.resolve().is_relative_to(REPO):
            raise RuntimeError(f"Unsafe participant archive source: {name}")
    baseline = SESSION / "lab/settlement-starter.pkb.sql"
    working = SESSION / "lab/settlement.pkb.sql"
    if working.read_bytes() != baseline.read_bytes():
        raise RuntimeError(
            "Participant source settlement.pkb.sql differs from the immutable starter. "
            "Do not package a completed participant solution."
        )
    with (REPO / "slides/session-2.pdf").open("rb") as pdf:
        if not pdf.read(8).startswith(b"%PDF-"):
            raise RuntimeError("slides/session-2.pdf is not a PDF.")
    return files


def validate_zip(archive: Path, expected_names: set[str]) -> None:
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise RuntimeError("ZIP contents do not match the participant allowlist.")
        if any(forbidden(name) for name in names):
            raise RuntimeError("ZIP contains a forbidden path.")
        corrupted = bundle.testzip()
        if corrupted:
            raise RuntimeError(f"ZIP integrity check failed: {corrupted}")
        if bundle.read("training/session-2/lab/settlement.pkb.sql") != bundle.read(
            "training/session-2/lab/settlement-starter.pkb.sql"
        ):
            raise RuntimeError("ZIP working package body is not the starter.")


def git_environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES", "BASH_ENV"):
        env.pop(key, None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_checked(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError("Extracted workspace check failed:\n" + result.stdout + result.stderr)
    return result.stdout


def verify_extracted_setup(archive: Path) -> None:
    # Cleanup is restricted to this newly created directory under system temp.
    with tempfile.TemporaryDirectory(prefix="session2-package-verify-") as directory:
        root = Path(directory).resolve()
        if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise RuntimeError("Unexpected temporary directory location.")
        with zipfile.ZipFile(archive) as bundle:
            # Every member name was checked against the allowlist before extraction.
            bundle.extractall(root)
        env = git_environment()
        output = run_checked(
            [sys.executable, "training/session-2/setup-workspace.py"], cwd=root, env=env,
        )
        if "WORKSPACE_READY " not in output:
            raise RuntimeError("Extracted setup did not report WORKSPACE_READY.")
        workspace = root / "training/session-2/workspace"
        status = run_checked(["git", "-C", str(workspace), "status", "--porcelain"], cwd=root, env=env)
        commits = run_checked(
            ["git", "-C", str(workspace), "rev-list", "--count", "HEAD"], cwd=root, env=env,
        )
        if status.strip() or commits.strip() != "1":
            raise RuntimeError("Extracted participant workspace lacks a clean baseline commit.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ required")
    if not shutil.which("git"):
        parser.error("Git is required to verify the extracted participant workspace.")
    output = args.output.resolve()
    if output.suffix.lower() != ".zip":
        parser.error("--output must name a .zip file")
    temporary = None
    try:
        files = collect_files()
        expected_names = {*files, "START-HERE.md", "START-HERE.html"}
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=output.stem + ".", suffix=".tmp",
                                         dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            bundle.writestr("START-HERE.md", START_HERE.encode("utf-8"))
            bundle.writestr("START-HERE.html", START_HERE_HTML.encode("utf-8"))
            for name, source in sorted(files.items()):
                bundle.write(source, name)
        validate_zip(temporary, expected_names)
        verify_extracted_setup(temporary)
        os.replace(temporary, output)
        temporary = None
        print(f"PARTICIPANT_PACKAGE_READY {output}")
        print(f"Verified {len(expected_names)} files; {output.stat().st_size} bytes.")
        print("ZIP allowlist, integrity, starter body and extracted clean Git baseline: PASS")
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired, zipfile.BadZipFile) as error:
        print(f"PACKAGE_ERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
