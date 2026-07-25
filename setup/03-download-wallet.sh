#!/usr/bin/env bash
#
# Завантажує wallet (client credentials) навчальної БД.
# Цей файл роздається всім 5 учасникам — wallet прив'язаний до бази, не до користувача.
#
# Запуск:  ./03-download-wallet.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$SCRIPT_DIR/.secrets"
WALLET_PWD_FILE="$SECRETS_DIR/wallet-password"
WALLET_FILE="$SCRIPT_DIR/wallet.zip"

DB_NAME="${DB_NAME:-ACORDTRAIN}"

command -v oci >/dev/null || { echo "ПОМИЛКА: oci CLI не знайдено в PATH." >&2; exit 1; }
[[ -f "$WALLET_PWD_FILE" ]] || { echo "ПОМИЛКА: немає $WALLET_PWD_FILE. Запустіть 00-generate-secrets.sh" >&2; exit 1; }

# Compartment: явно заданий → $OCI_TENANCY (Cloud Shell) → ~/.oci/config (локально)
if [[ -z "${COMPARTMENT_OCID:-}" ]]; then
  if [[ -n "${OCI_TENANCY:-}" ]]; then
    COMPARTMENT_OCID="$OCI_TENANCY"
  elif [[ -f "$HOME/.oci/config" ]]; then
    COMPARTMENT_OCID="$(grep -E '^tenancy' "$HOME/.oci/config" | head -1 | cut -d= -f2 | tr -d ' ')"
  fi
fi

[[ -n "${COMPARTMENT_OCID:-}" ]] || {
  echo "ПОМИЛКА: не вдалося визначити compartment. Задайте COMPARTMENT_OCID вручну." >&2; exit 1; }

ADB_OCID="$(oci db autonomous-database list \
  --compartment-id "$COMPARTMENT_OCID" \
  --query "data[?\"db-name\"=='$DB_NAME' && \"lifecycle-state\"=='AVAILABLE'] | [0].id" \
  --raw-output)"

[[ -n "$ADB_OCID" && "$ADB_OCID" != "null" ]] || {
  echo "ПОМИЛКА: не знайдено доступну БД з іменем '$DB_NAME'." >&2; exit 1; }

echo "БД знайдено: $ADB_OCID"

oci db autonomous-database generate-wallet \
  --autonomous-database-id "$ADB_OCID" \
  --password "$(cat "$WALLET_PWD_FILE")" \
  --file "$WALLET_FILE"

echo
echo "Wallet збережено: $WALLET_FILE"
echo "Пароль wallet:    $WALLET_PWD_FILE"
echo
echo "Роздати учасникам разом з їхніми логінами. Приклад підключення:"
echo "  conn -save train -savepwd TRAINEE1/<pwd>@${DB_NAME,,}_low"
