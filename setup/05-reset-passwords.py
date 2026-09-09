#!/usr/bin/env python3
"""
Перевипуск паролів користувачів навчальної БД.

Запуск:
    python setup/05-reset-passwords.py

Передумови:
    setup/.secrets/adb-admin-password   пароль ADMIN
    setup/.secrets/users.txt            НОВІ паролі у форматі LOGIN:PASSWORD
    setup/.secrets/wallet-password      пароль wallet
    .wallet/                            розпакований wallet ADB

Використовує python-oracledb у thin-режимі: без Oracle Client і без Java.

Жоден пароль не друкується. Кожен новий пароль перевіряється справжнім
підключенням — успішний ALTER USER сам по собі нічого не доводить.
"""

import os
import sys
import zipfile
from pathlib import Path

try:
    import oracledb
except ImportError:
    sys.exit("Немає модуля oracledb. Встановіть:  python -m pip install oracledb")

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "setup" / ".secrets"
WALLET_DIR = ROOT / ".wallet"
DSN = os.environ.get("ADB_SERVICE", "acordtrain_low")

OK, FAIL, WARN = "  [ OK ]", "  [FAIL]", "  [WARN]"


def read_secret(name: str) -> str:
    path = SECRETS / name
    if not path.is_file() or path.stat().st_size == 0:
        sys.exit(f"Немає або порожній: {path}")
    return path.read_text(encoding="utf-8").strip()


def prepare_wallet() -> Path:
    """Повертає каталог, придатний для thin-режиму.

    Thin-режим читає ewallet.pem. Якщо в каталозі лежить лише архів wallet.zip -
    розпаковуємо. Якщо pem немає взагалі, кажемо про це прямо, а не падаємо
    з незрозумілою помилкою TLS.
    """
    if not WALLET_DIR.is_dir():
        sys.exit(f"Немає каталогу {WALLET_DIR}. Розпакуйте туди wallet.")

    zips = list(WALLET_DIR.glob("*.zip"))
    if zips and not (WALLET_DIR / "tnsnames.ora").exists():
        with zipfile.ZipFile(zips[0]) as z:
            z.extractall(WALLET_DIR)
        print(f"{OK} wallet розпаковано з {zips[0].name}")

    if not (WALLET_DIR / "tnsnames.ora").exists():
        sys.exit(f"У {WALLET_DIR} немає tnsnames.ora - це не схоже на wallet ADB.")

    if not (WALLET_DIR / "ewallet.pem").exists():
        sys.exit(
            f"У wallet немає ewallet.pem, а thin-режим потребує саме його.\n"
            f"Сконвертуйте з p12 (openssl іде в комплекті з Git):\n"
            f'  openssl pkcs12 -in "{WALLET_DIR / "ewallet.p12"}" '
            f'-out "{WALLET_DIR / "ewallet.pem"}" -nodes'
        )
    return WALLET_DIR


def check_policy(login: str, password: str) -> str | None:
    """Правила профілю ADB. Повертає причину відмови або None.

    Найпідступніше з них — заборона на входження імені користувача в пароль,
    і саме як ПІДРЯДКИ. Пароль 'AcordBank2026xS' виглядає бездоганно, але для
    користувача CO відхиляється, бо 'co' сидить усередині 'Acord'. Ловимо це
    тут, а не за ORA-28219 після половини виконаних змін.
    """
    if not 12 <= len(password) <= 30:
        return f"довжина {len(password)}, треба 12-30"
    if not any(c.isupper() for c in password):
        return "немає великої літери"
    if not any(c.islower() for c in password):
        return "немає малої літери"
    if not any(c.isdigit() for c in password):
        return "немає цифри"
    if '"' in password:
        return "містить подвійну лапку"
    if login.lower() in password.lower():
        return f"містить ім'я користувача '{login}' як підрядок"
    return None


def connect(user: str, password: str, wallet_dir: Path, wallet_pw: str):
    return oracledb.connect(
        user=user,
        password=password,
        dsn=DSN,
        config_dir=str(wallet_dir),
        wallet_location=str(wallet_dir),
        wallet_password=wallet_pw,
    )


def main() -> int:
    admin_pw = read_secret("adb-admin-password")
    wallet_pw = read_secret("wallet-password")
    schema_pw = read_secret("sample-schema-password")

    users = []
    for line in read_secret("users.txt").splitlines():
        if ":" in line:
            login, pwd = line.split(":", 1)
            users.append((login.strip(), pwd.strip()))
    if not users:
        sys.exit("users.txt порожній або має неочікуваний формат")

    wallet_dir = prepare_wallet()

    print("\n1. Підключення як ADMIN")
    try:
        admin = connect("ADMIN", admin_pw, wallet_dir, wallet_pw)
    except oracledb.Error as e:
        (err,) = e.args
        print(f"{FAIL} {err.message.splitlines()[0]}")
        print("\n  Якщо це таймаут - база могла зупинитись (Always Free, 7 днів простою).")
        print("  Якщо ORA-01017 - невірний пароль ADMIN у setup/.secrets/.")
        return 1

    with admin:
        cur = admin.cursor()
        cur.execute("select banner_full from v$version")
        print(f"{OK} {cur.fetchone()[0].splitlines()[0]}")

        print("\n2. Перевірка паролів проти правил профілю ADB")
        targets = users + [("HR", schema_pw), ("CO", schema_pw)]
        rejected = [(u, r) for u, p in targets if (r := check_policy(u, p))]
        if rejected:
            for login, reason in rejected:
                print(f"{FAIL} {login:<10} {reason}")
            print("\n  Нічого не змінено. Виправте паролі й запустіть знову.")
            return 1
        print(f"{OK} усі {len(targets)} паролів відповідають правилам")

        print("\n3. Перевипуск паролів")
        changed = []
        for login, new_pw in targets:
            cur.execute(
                "select count(*) from dba_users where username = :u",
                u=login.upper(),
            )
            if cur.fetchone()[0] == 0:
                print(f'{WARN} {login:<10} немає такого користувача - пропускаємо')
                continue
            try:
                # Пароль у подвійних лапках: так Oracle бере його буквально.
                cur.execute(f'alter user "{login.upper()}" identified by "{new_pw}"')
                cur.execute(f'alter user "{login.upper()}" account unlock')
                print(f"{OK} {login:<10} пароль змінено")
                changed.append((login, new_pw))
            except oracledb.Error as e:
                (err,) = e.args
                # ORA-28007 означає, що цей пароль у користувача ВЖЕ стоїть.
                # Для повторного запуску це не помилка, а підтвердження стану,
                # інакше скрипт неможливо було б запустити двічі.
                if err.code == 28007:
                    cur.execute(f'alter user "{login.upper()}" account unlock')
                    print(f"{OK} {login:<10} пароль уже встановлено раніше")
                    changed.append((login, new_pw))
                else:
                    print(f"{FAIL} {login:<10} {err.message.splitlines()[0]}")

    print("\n4. Перевірка: підключаємось кожним користувачем НОВИМ паролем")
    good, bad = 0, 0
    for login, new_pw in changed:
        if login.upper() in ("HR", "CO"):
            # Власники схем навмисно лишаються без права connect - не перевіряємо
            continue
        try:
            with connect(login, new_pw, wallet_dir, wallet_pw) as c:
                cur = c.cursor()
                cur.execute("select user from dual")
                who = cur.fetchone()[0]
            if who.upper() == login.upper():
                print(f"{OK} {login:<10} вхід працює, підключення як {who}")
                good += 1
            else:
                print(f"{FAIL} {login:<10} увійшли як {who}")
                bad += 1
        except oracledb.Error as e:
            (err,) = e.args
            print(f"{FAIL} {login:<10} {err.message.splitlines()[0]}")
            bad += 1

    print(f"\nПідсумок: працює {good}, не працює {bad}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
