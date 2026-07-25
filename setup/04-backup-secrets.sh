#!/usr/bin/env bash
#
# Збирає всі доступи навчального середовища в ОДИН зашифрований файл.
#
# Запуск:  ./04-backup-secrets.sh
#
# Скрипт запитає парольну фразу — її вводите ВИ, вона нікуди не записується.
# Збережіть її окремо (менеджер паролів): без неї архів не відкрити.
#
# Відкрити пізніше (Git Bash / Linux / macOS):
#   gpg -d acordbank-secrets.gpg | tar xzf - -C ./restored
#
# Жоден пароль не виводиться на екран.

set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

OUT="${BACKUP_OUT:-$HOME/acordbank-secrets.gpg}"
TMP_OUT="$OUT.new.$$"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$TMP_OUT"' EXIT
chmod 700 "$STAGE"

command -v gpg >/dev/null || die "gpg не знайдено"
[[ -d "$SECRETS_DIR" ]] || die "немає $SECRETS_DIR"

# --- 1. Повнота ПЕРЕД шифруванням ----------------------------------------
# Неповний архів гірший за його відсутність: він створює хибну впевненість.
# Тому бракуючі складові — помилка, а не попередження.

MISSING=()
for f in adb-admin-password wallet-password sample-schema-password users.txt; do
  [[ -s "$SECRETS_DIR/$f" ]] || MISSING+=("$f")
done
[[ -s "$WALLET_FILE" ]] || MISSING+=("wallet.zip")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  die "бракує складових: ${MISSING[*]}
     Спершу виконайте 00-generate-secrets.sh і 03-download-wallet.sh.
     Резервну копію робимо лише повною."
fi

# --- 2. Збираємо ----------------------------------------------------------

ADB_OCID="$(oci db autonomous-database list \
  --compartment-id "$(resolve_compartment)" \
  --query "data[?\"db-name\"=='$DB_NAME'] | [0].id" --raw-output 2>/dev/null || echo '(не визначено)')"

{
  echo "AcordBank - Claude Code + Oracle training environment"
  echo "Credentials backup, created: $(date -u '+%Y-%m-%d %H:%M') UTC"
  echo
  echo "[ORACLE CLOUD]"
  echo "Tenancy OCID : ${OCI_TENANCY:-(not detected)}"
  echo "Region       : ${OCI_REGION:-(not detected)}"
  echo "ADB OCID     : $ADB_OCID"
  echo "DB name      : $DB_NAME"
  echo "Service      : $DB_SERVICE   (_low limits per-query parallelism)"
  echo
  echo "[DB PASSWORDS]"
  echo "ADMIN                : $(cat "$SECRETS_DIR/adb-admin-password")"
  echo "Wallet password      : $(cat "$SECRETS_DIR/wallet-password")"
  echo "HR/CO schema owners  : $(cat "$SECRETS_DIR/sample-schema-password")"
  echo
  echo "[USERS  login:password]"
  cat "$SECRETS_DIR/users.txt"
  echo "TRAINEE1-5 = participants, own schema each. TRAINER = trainer demo schema."
  echo
  echo "[GITHUB]"
  echo "Repo: https://github.com/koldovsky/acordbank-oracle-training"
  echo "Repo-level secrets: ADB_WALLET_B64, ADB_SERVICE=$DB_SERVICE"
  echo "User-level secrets: ADB_USER, ADB_PASSWORD  (each person sets own)"
  echo
  echo "[RECOVERY]"
  echo "ADMIN pwd : OCI console -> ADB -> More actions -> Administrator password"
  echo "Wallet    : regenerate via setup/03-download-wallet.sh"
  echo "User pwd  : as ADMIN run  ALTER USER x IDENTIFIED BY \"y\""
  echo "Nothing here is unrecoverable - this is a convenience copy, not a single point of failure."
} > "$STAGE/CREDENTIALS.txt"

cp "$WALLET_FILE" "$STAGE/wallet.zip"
log "зібрано: $(ls "$STAGE" | tr '\n' ' ')"

# --- 3. Шифруємо у ТИМЧАСОВИЙ файл ---------------------------------------
# Наявну копію не чіпаємо, доки нова не пройде перевірку.

echo
echo "УВАГА: без pinentry gpg питає фразу ОДИН раз, без підтвердження."
echo "Друкарська помилка мовчки стане паролем — тому нижче обов'язкова перевірка."
echo

tar czf - -C "$STAGE" . \
  | gpg --symmetric --pinentry-mode loopback \
        --cipher-algo AES256 --s2k-digest-algo SHA512 -o "$TMP_OUT"

# --- 4. Перевірка розшифруванням -----------------------------------------
# Скидання кешу агента тут КРИТИЧНЕ: без нього gpg візьме фразу з кешу
# й розшифрує успішно навіть тоді, коли ви ввели не те, що думаєте.
# Перевірка без цього рядка не перевіряє нічого.

gpgconf --kill gpg-agent 2>/dev/null || true
sleep 1

echo "Перевірка: введіть ТУ САМУ фразу ще раз."
LISTING="$(gpg -d --pinentry-mode loopback "$TMP_OUT" 2>/dev/null | tar tzf - 2>/dev/null || true)"

for required in CREDENTIALS.txt wallet.zip; do
  grep -q "$required" <<< "$LISTING" \
    || die "перевірка не пройшла: в архіві немає $required, або фраза невірна.
     Попередню копію НЕ змінено: ${OUT}"
done

# --- 5. Атомарна заміна ---------------------------------------------------

mv -f "$TMP_OUT" "$OUT"
chmod 600 "$OUT" 2>/dev/null || true

echo
echo "OK — архів повний і відкривається цією фразою."
echo "Файл: $OUT ($(stat -c%s "$OUT") байт)"
echo "Відкрити:  gpg -d '$OUT' | tar xzf - -C ./restored"
