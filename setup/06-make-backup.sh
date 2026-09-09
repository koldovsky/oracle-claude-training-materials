#!/usr/bin/env bash
#
# Створює новий зашифрований архів доступів навчального середовища.
#
# Запуск:  bash setup/06-make-backup.sh
#
# Відмінність від 04-backup-secrets.sh: парольна фраза береться з файлу
# setup/.secrets/backup-passphrase, а не питається інтерактивно. Це свідомий
# вибір для навчального середовища - фразу неможливо забути чи набрати з
# одруком, а перевірка розшифруванням стає справді автоматичною.
#
# Відкрити архів потім:
#   gpg -d acordbank-secrets.gpg | tar xzf - -C ./restored

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS="$ROOT/setup/.secrets"
WALLET_DIR="$ROOT/.wallet"
OUT="${BACKUP_OUT:-$ROOT/acordbank-secrets.gpg}"
TMP_OUT="$OUT.new.$$"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE" "$TMP_OUT"' EXIT
chmod 700 "$STAGE"

die() { echo "ПОМИЛКА: $*" >&2; exit 1; }
log() { echo "  $*"; }

command -v gpg >/dev/null || die "gpg не знайдено (він іде в комплекті з Git)"

# --- 1. Повнота ПЕРЕД шифруванням ----------------------------------------
# Неповний архів гірший за його відсутність: він створює хибну впевненість.

MISSING=()
for f in adb-admin-password wallet-password sample-schema-password users.txt backup-passphrase; do
  [[ -s "$SECRETS/$f" ]] || MISSING+=("setup/.secrets/$f")
done

WALLET_ZIP=""
for cand in "$WALLET_DIR/wallet.zip" "$WALLET_DIR"/*.zip; do
  [[ -s "$cand" ]] && { WALLET_ZIP="$cand"; break; }
done
[[ -n "$WALLET_ZIP" ]] || MISSING+=(".wallet/wallet.zip")

if [[ ${#MISSING[@]} -gt 0 ]]; then
  die "бракує складових:
     $(printf '%s\n     ' "${MISSING[@]}")
Резервну копію робимо лише повною."
fi

PASSPHRASE_FILE="$SECRETS/backup-passphrase"

# --- 2. Збираємо ----------------------------------------------------------

{
  echo "AcordBank - Claude Code + Oracle training environment"
  echo "Credentials backup, created: $(date -u '+%Y-%m-%d %H:%M') UTC"
  echo
  echo "[ORACLE CLOUD]"
  echo "DB name      : ACORDTRAIN   (Oracle 19c, Always Free, eu-frankfurt-1)"
  echo "Service      : acordtrain_low   (_low limits per-query parallelism)"
  echo "Console      : https://cloud.oracle.com/db/adb?region=eu-frankfurt-1"
  echo
  echo "[ARCHIVE PASSPHRASE]"
  echo "This archive is encrypted with: $(cat "$PASSPHRASE_FILE")"
  echo "Deliberately simple: training environment, synthetic data only."
  echo
  echo "[DB PASSWORDS]"
  echo "ADMIN                : $(cat "$SECRETS/adb-admin-password")"
  echo "Wallet password      : $(cat "$SECRETS/wallet-password")"
  echo "HR/CO schema owners  : $(cat "$SECRETS/sample-schema-password")"
  echo
  echo "[USERS  login:password]"
  cat "$SECRETS/users.txt"
  echo
  echo "TRAINEE1-5 = participants, own schema each. TRAINER = trainer demo schema."
  echo
  echo "[RECOVERY]"
  echo "ADMIN pwd : OCI console -> ADB -> More actions -> Administrator password"
  echo "Wallet    : OCI console -> ADB -> Database connection -> Download wallet"
  echo "User pwd  : as ADMIN run  ALTER USER x IDENTIFIED BY \"y\""
  echo "            or re-run  python setup/05-reset-passwords.py"
  echo "Nothing here is unrecoverable - this is a convenience copy."
} > "$STAGE/CREDENTIALS.txt"

cp "$WALLET_ZIP" "$STAGE/wallet.zip"
log "зібрано: $(ls "$STAGE" | tr '\n' ' ')"

# --- 3. Шифруємо у ТИМЧАСОВИЙ файл ---------------------------------------
# Наявну копію не чіпаємо, доки нова не пройде перевірку.

tar czf - -C "$STAGE" . \
  | gpg --batch --yes --symmetric \
        --passphrase-file "$PASSPHRASE_FILE" --pinentry-mode loopback \
        --cipher-algo AES256 --s2k-digest-algo SHA512 -o "$TMP_OUT"

# --- 4. Перевірка розшифруванням -----------------------------------------
# Кеш агента скидаємо: інакше перевірка пройшла б на кеші й нічого б не довела.

gpgconf --kill gpg-agent 2>/dev/null || true

LISTING="$(gpg --batch --quiet --decrypt \
             --passphrase-file "$PASSPHRASE_FILE" --pinentry-mode loopback \
             "$TMP_OUT" 2>/dev/null | tar tzf - 2>/dev/null || true)"

for required in CREDENTIALS.txt wallet.zip; do
  grep -q "$required" <<< "$LISTING" \
    || die "перевірка не пройшла: в архіві немає $required.
     Попередню копію НЕ змінено: $OUT"
done

# --- 5. Атомарна заміна ---------------------------------------------------

mv -f "$TMP_OUT" "$OUT"
chmod 600 "$OUT" 2>/dev/null || true

echo
echo "OK - архів повний і перевірений розшифруванням."
echo "Файл:  $OUT  ($(wc -c < "$OUT") байт)"
echo "Фраза: у setup/.secrets/backup-passphrase"
echo
echo "Відкрити:  gpg -d '$OUT' | tar xzf - -C ./restored"
