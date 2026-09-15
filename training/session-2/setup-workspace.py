#!/usr/bin/env python3
"""Create a fresh, independent Session 2 workspace. Never overwrite existing work."""
import argparse
import json
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SOURCE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", nargs="?", type=Path, default=SOURCE / "workspace")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ required")
    if destination.exists():
        parser.error(f"Already exists: {destination}. Choose a NEW destination; existing work is preserved.")
    if not shutil.which("git"):
        parser.error("Git is required to create an independent project root.")
    for required in (SOURCE / "lab" / "install.sql", SOURCE / "extensions" / ".claude" / "settings.json"):
        if not required.is_file():
            parser.error(f"Incomplete course bundle: {required}")
    destination.mkdir(parents=True)
    shutil.copytree(SOURCE / "lab", destination / "lab", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(SOURCE / "extensions" / ".claude", destination / ".claude", ignore=shutil.ignore_patterns("__pycache__"))
    # The participant may invoke python3 while no `python` alias exists.
    # Bind the generated hook to the exact interpreter that created the workspace.
    settings_path = destination / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    interpreter = shlex.quote(Path(sys.executable).as_posix())
    for matcher in settings["hooks"]["PreToolUse"]:
        for hook in matcher["hooks"]:
            hook["command"] = interpreter + ' "${CLAUDE_PROJECT_DIR}/.claude/hooks/sql_guard.py"'
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (destination / ".mcp.json").write_text(json.dumps({"mcpServers": {"sqlcl": {"command": "sql", "args": ["-mcp"]}}}, indent=2) + "\n", encoding="utf-8")
    (destination / ".gitignore").write_text(".claude/settings.local.json\n*.log\n__pycache__/\n", encoding="utf-8")
    (destination / "CLAUDE.md").write_text("""# Сесія 2: навчальна лабораторія

Працюй українською. У lab/ лише синтетичні навчальні дані.
Контракт задачі: lab/SPEC.md. Редагуємо реалізацію пакета, тести є незалежним критерієм.
Читай тільки потрібні файли. Результати запуску відокремлюй від припущень.
Спільні HR, CO, SH не змінюємо. Працюємо лише з об'єктами S2_ своєї навчальної схеми.
Не читай файли доступів або матеріали тренера поза цим проєктом.
Hook перевіряє лише Write/Edit SQL у lab/; він не контролює SQLcl, Bash чи довільний SQL.
Для рев'ю доступні /oracle-lab-review та підлеглий агент oracle-reviewer.
""", encoding="utf-8")
    git_commands = [
        ["git", "init", "--quiet", "--initial-branch=main", str(destination)],
        ["git", "-C", str(destination), "add", "."],
        ["git", "-C", str(destination), "-c", "user.name=Session 2 Lab",
         "-c", "user.email=session2@example.invalid", "-c", "commit.gpgsign=false",
         "commit", "--quiet", "-m", "Session 2 starter baseline"],
    ]
    for command in git_commands:
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            print("Files copied, but Git baseline setup failed. Inspect destination before retrying.", file=sys.stderr)
            return 1
    print(f"WORKSPACE_READY {destination}")
    print("cd \"" + str(destination) + "\"")
    print("sql -S -name train @lab/install.sql")
    print("sql -S -name train @lab/verify-baseline.sql")
    print("claude")
    print("Trainer answers were not copied. Existing project settings were not changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
