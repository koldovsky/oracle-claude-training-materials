#!/usr/bin/env python3
"""
Вивантажує DDL навчальних схем HR і CO у файлову структуру, придатну для git.

Запуск:  python setup/07-export-ddl.py

Саме цей каталог учасники відкривають у Claude Code на занятті: він дає
можливість читати схему, шукати по ній і оцінювати наслідки змін, не маючи
підключення до бази. Підключення потрібне лише щоб перевірити гіпотезу.

Результат:  db/<СХЕМА>/<тип>/<ОБ'ЄКТ>.sql
"""

import pathlib
import sys

try:
    import oracledb
except ImportError:
    sys.exit("Немає модуля oracledb:  python -m pip install oracledb")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECRETS = ROOT / "setup" / ".secrets"
WALLET = ROOT / ".wallet"
OUT = ROOT / "db"

SCHEMAS = ("HR", "CO")

# Порядок важливий: таблиці читають найчастіше, тож вони першими в каталозі.
KINDS = (
    ("TABLE", "tables"),
    ("VIEW", "views"),
    ("PROCEDURE", "procedures"),
    ("FUNCTION", "functions"),
    ("PACKAGE", "packages"),
    ("TRIGGER", "triggers"),
    ("SEQUENCE", "sequences"),
    ("INDEX", "indexes"),
)


def secret(name):
    return (SECRETS / name).read_text(encoding="utf-8").strip()


def main():
    conn = oracledb.connect(
        user="ADMIN",
        password=secret("adb-admin-password"),
        dsn="acordtrain_low",
        config_dir=str(WALLET),
        wallet_location=str(WALLET),
        wallet_password=secret("wallet-password"),
    )

    with conn:
        cur = conn.cursor()

        # Прибираємо все, що робить DDL нечитабельним: табличні простори,
        # параметри зберігання, сегменти. Учаснику потрібна структура,
        # а не фізичні атрибути.
        for opt in ("SEGMENT_ATTRIBUTES", "STORAGE", "TABLESPACE"):
            cur.callproc("dbms_metadata.set_transform_param",
                         [-1, opt, False])
        cur.callproc("dbms_metadata.set_transform_param",
                     [-1, "SQLTERMINATOR", True])
        cur.callproc("dbms_metadata.set_transform_param",
                     [-1, "PRETTY", True])

        total = 0
        for schema in SCHEMAS:
            for obj_type, folder in KINDS:
                cur.execute(
                    """select object_name from dba_objects
                        where owner = :o and object_type = :t
                          and generated = 'N'
                        order by object_name""",
                    o=schema, t=obj_type,
                )
                names = [r[0] for r in cur]
                if not names:
                    continue

                target = OUT / schema / folder
                target.mkdir(parents=True, exist_ok=True)

                for name in names:
                    try:
                        cur.execute(
                            "select dbms_metadata.get_ddl(:t, :n, :o) from dual",
                            t=obj_type, n=name, o=schema,
                        )
                        ddl = cur.fetchone()[0]
                        if hasattr(ddl, "read"):
                            ddl = ddl.read()
                    except oracledb.Error as e:
                        print(f"   ПРОПУЩЕНО {schema}.{name}: "
                              f"{e.args[0].message.splitlines()[0]}")
                        continue

                    text = ddl.strip()

                    # Коментарі до таблиці й колонок лежать окремо від DDL,
                    # але саме вони найцінніші для орієнтації в схемі.
                    if obj_type == "TABLE":
                        text += "\n" + comments(cur, schema, name)

                    (target / f"{name}.sql").write_text(
                        text + "\n", encoding="utf-8")
                    total += 1

                print(f"   {schema}/{folder:<12} {len(names)}")

    print(f"\nЗаписано об'єктів: {total}")
    print(f"Каталог: {OUT}")


def comments(cur, schema, table):
    out = []
    cur.execute(
        """select comments from all_tab_comments
            where owner = :o and table_name = :t and comments is not null""",
        o=schema, t=table)
    for (c,) in cur:
        out.append(f'COMMENT ON TABLE "{schema}"."{table}" IS '
                   f"'{c.replace(chr(39), chr(39) * 2)}';")

    cur.execute(
        """select column_name, comments from all_col_comments
            where owner = :o and table_name = :t and comments is not null
            order by column_name""",
        o=schema, t=table)
    for col, c in cur:
        out.append(f'COMMENT ON COLUMN "{schema}"."{table}"."{col}" IS '
                   f"'{c.replace(chr(39), chr(39) * 2)}';")

    if not out:
        return "\n-- Коментарів до цієї таблиці в базі немає.\n"
    return "\n" + "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
