#!/usr/bin/env bash
#
# Завантажує wallet (client credentials) навчальної БД.
# Цей файл роздається всім учасникам — wallet прив'язаний до бази, не до користувача.
#
# Запуск:  ./03-download-wallet.sh

set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

command -v oci >/dev/null || die "oci CLI не знайдено в PATH"

WALLET_PWD="$(need_secret wallet-password)"
COMPARTMENT_OCID="$(resolve_compartment)"

ADB_OCID="$(oci db autonomous-database list \
  --compartment-id "$COMPARTMENT_OCID" \
  --query "data[?\"db-name\"=='$DB_NAME' && \"lifecycle-state\"=='AVAILABLE'] | [0].id" \
  --raw-output 2>/dev/null)" || die "не вдалося отримати перелік баз"

[[ -n "$ADB_OCID" && "$ADB_OCID" != "null" ]] \
  || die "не знайдено доступну БД з іменем '$DB_NAME'"

log "БД знайдено: $ADB_OCID"

mkdir -p "$SECRETS_DIR"
oci db autonomous-database generate-wallet \
  --autonomous-database-id "$ADB_OCID" \
  --password "$WALLET_PWD" \
  --file "$WALLET_FILE" > /dev/null

unzip -tq "$WALLET_FILE" >/dev/null 2>&1 || die "отриманий wallet не є коректним zip"
chmod 600 "$WALLET_FILE" 2>/dev/null || true

echo
echo "Wallet збережено: $WALLET_FILE ($(stat -c%s "$WALLET_FILE") байт)"
echo
echo "Для секрету GitHub:  base64 -w0 '$WALLET_FILE'"
echo "Далі:  ./02-create-users.sh"
