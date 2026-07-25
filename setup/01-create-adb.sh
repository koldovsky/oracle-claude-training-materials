#!/usr/bin/env bash
#
# Створення навчальної Oracle Autonomous Database (Always Free).
#
# Передумови:
#   1. Встановлений OCI CLI:  https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm
#   2. Виконано `oci setup config` (або налаштована автентифікація іншим способом)
#
# Запуск:
#   ./01-create-adb.sh
#
# Пароль ADMIN береться з setup/.secrets/adb-admin-password.
# Якщо файлу немає — скрипт сам викличе 00-generate-secrets.sh.
# Пароль ніде не виводиться на екран і не потрапляє в логи.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$SCRIPT_DIR/.secrets"
PWD_FILE="$SECRETS_DIR/adb-admin-password"

DB_NAME="${DB_NAME:-ACORDTRAIN}"          # макс. 14 символів, лише літери й цифри
DISPLAY_NAME="${DISPLAY_NAME:-AcordBank Training}"

# ---------- перевірки перед створенням ----------

command -v oci >/dev/null || { echo "ПОМИЛКА: oci CLI не знайдено в PATH." >&2; exit 1; }

if [[ ! -f "$PWD_FILE" ]]; then
  echo "Пароль ADMIN ще не згенеровано — запускаємо 00-generate-secrets.sh"
  "$SCRIPT_DIR/00-generate-secrets.sh"
  echo
fi

ADB_ADMIN_PASSWORD="$(cat "$PWD_FILE")"

if [[ ${#ADB_ADMIN_PASSWORD} -lt 12 || ${#ADB_ADMIN_PASSWORD} -gt 30 ]]; then
  echo "ПОМИЛКА: пароль у $PWD_FILE має бути 12-30 символів." >&2
  exit 1
fi

# Compartment: явно заданий → $OCI_TENANCY → ~/.oci/config
#
# У Cloud Shell файлу ~/.oci/config НЕМАЄ: автентифікація йде делегованим
# токеном сесії, а OCID тенанта лежить у змінній OCI_TENANCY.
# Локально ж навпаки — є config, а змінної немає.
if [[ -z "${COMPARTMENT_OCID:-}" ]]; then
  if [[ -n "${OCI_TENANCY:-}" ]]; then
    COMPARTMENT_OCID="$OCI_TENANCY"
  elif [[ -f "$HOME/.oci/config" ]]; then
    COMPARTMENT_OCID="$(grep -E '^tenancy' "$HOME/.oci/config" | head -1 | cut -d= -f2 | tr -d ' ')"
  fi
fi

if [[ -z "${COMPARTMENT_OCID:-}" ]]; then
  echo "ПОМИЛКА: не вдалося визначити compartment." >&2
  echo "Задайте вручну:  export COMPARTMENT_OCID='ocid1.compartment.oc1..…'" >&2
  exit 1
fi
echo "Compartment: $COMPARTMENT_OCID"

# ---------- ключова перевірка: чи є вільний слот Always Free ----------
# Always Free дає лише 2 інстанси на тенант. Якщо ліміт вичерпано, створення
# без цієї перевірки мовчки зробить ПЛАТНУ базу.

FREE_COUNT="$(oci db autonomous-database list \
  --compartment-id "$COMPARTMENT_OCID" \
  --query "length(data[?\"is-free-tier\"==\`true\` && \"lifecycle-state\"!='TERMINATED'])" \
  --raw-output 2>/dev/null || echo 0)"

echo "Наявних Always Free баз: $FREE_COUNT з 2"
if [[ "$FREE_COUNT" -ge 2 ]]; then
  echo "ПОМИЛКА: ліміт Always Free вичерпано. Створення зупинено, щоб не отримати платний інстанс." >&2
  echo "Видаліть непотрібну базу або використайте наявну." >&2
  exit 1
fi

# ---------- створення ----------

echo "Створюємо '$DISPLAY_NAME' ($DB_NAME)..."

oci db autonomous-database create \
  --compartment-id "$COMPARTMENT_OCID" \
  --db-name "$DB_NAME" \
  --display-name "$DISPLAY_NAME" \
  --db-workload OLTP \
  --is-free-tier true \
  --cpu-core-count 1 \
  --data-storage-size-in-tbs 1 \
  --admin-password "$ADB_ADMIN_PASSWORD" \
  --wait-for-state AVAILABLE

echo
echo "Готово. Наступні кроки:"
echo "  1. ./03-download-wallet.sh          — завантажити wallet"
echo "  2. 02-training-users.sql від ADMIN  — створити 5 схем для учасників"
echo
echo "Пароль ADMIN: $PWD_FILE"
