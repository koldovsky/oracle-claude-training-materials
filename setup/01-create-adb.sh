#!/usr/bin/env bash
#
# Створення навчальної Oracle Autonomous Database (Always Free).
#
# Передумови:
#   1. OCI CLI (у Cloud Shell уже є й автентифікований — найпростіший шлях)
#   2. ./00-generate-secrets.sh виконано
#
# Запуск:  ./01-create-adb.sh
#
# Пароль ADMIN береться з каталогу секретів, на екран не виводиться.

set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

DISPLAY_NAME="${DISPLAY_NAME:-AcordBank Training}"

command -v oci >/dev/null || die "oci CLI не знайдено в PATH"

ADMIN_PWD="$(need_secret adb-admin-password)"
[[ ${#ADMIN_PWD} -ge 12 && ${#ADMIN_PWD} -le 30 ]] \
  || die "пароль ADMIN має бути 12-30 символів"

COMPARTMENT_OCID="$(resolve_compartment)"
echo "Compartment: $COMPARTMENT_OCID"

# --- захист від випадкового ПЛАТНОГО інстансу ----------------------------
#
# Always Free дає 2 інстанси НА ТЕНАНТ. Якщо ліміт вичерпано, прапорець
# --is-free-tier не дає помилки, а створює платну базу.
#
# Перевірка навмисно "падає в закритий бік": якщо кількість НЕ вдалося
# отримати (немає прав, збій мережі, змінився формат виводу) — зупиняємось.
# Раніше тут було `|| echo 0`, і будь-який збій читався як «вільно» —
# тобто захист мовчки вимикався саме тоді, коли був найпотрібніший.
#
# Рахуємо по всьому тенанту, а не лише в поточному compartment.

TENANCY_OCID="${OCI_TENANCY:-$COMPARTMENT_OCID}"

echo "Перевіряємо ліміт Always Free по всьому тенанту..."
if ! FREE_JSON="$(oci db autonomous-database list \
      --compartment-id "$TENANCY_OCID" \
      --compartment-id-in-subtree true \
      --all 2>/dev/null)"; then
  die "не вдалося отримати перелік баз. Зупиняємось, щоб не створити ПЛАТНИЙ інстанс.
     Перевірте права й підключення, або задайте SKIP_FREE_CHECK=1 свідомо."
fi

FREE_COUNT="$(printf '%s' "$FREE_JSON" \
  | python3 -c 'import json,sys
d=json.load(sys.stdin).get("data",[])
print(sum(1 for x in d if x.get("is-free-tier") and x.get("lifecycle-state")!="TERMINATED"))' 2>/dev/null)" \
  || die "не вдалося порахувати наявні Always Free бази — зупиняємось"

echo "Наявних Always Free баз: $FREE_COUNT з 2"
if [[ "${SKIP_FREE_CHECK:-0}" != "1" && "$FREE_COUNT" -ge 2 ]]; then
  die "ліміт Always Free вичерпано. Створення зупинено, щоб не отримати платний інстанс.
     Видаліть непотрібну базу або використайте наявну."
fi

# Чи немає вже бази з таким іменем
if printf '%s' "$FREE_JSON" | grep -q "\"db-name\": \"$DB_NAME\""; then
  die "база з іменем $DB_NAME уже існує. Оберіть інше DB_NAME або використайте наявну."
fi

# --- створення -----------------------------------------------------------

echo "Створюємо '$DISPLAY_NAME' ($DB_NAME)..."

oci db autonomous-database create \
  --compartment-id "$COMPARTMENT_OCID" \
  --db-name "$DB_NAME" \
  --display-name "$DISPLAY_NAME" \
  --db-workload OLTP \
  --is-free-tier true \
  --cpu-core-count 1 \
  --data-storage-size-in-tbs 1 \
  --admin-password "$ADMIN_PWD" \
  --wait-for-state AVAILABLE > /dev/null

# --- перевірка ПІСЛЯ створення -------------------------------------------
# Довіряти прапорцю на вході недостатньо — переконуємось, що створене
# справді безкоштовне.

CREATED="$(oci db autonomous-database list \
  --compartment-id "$COMPARTMENT_OCID" \
  --query "data[?\"db-name\"=='$DB_NAME'] | [0].{free:\"is-free-tier\",state:\"lifecycle-state\",ver:\"db-version\"}" \
  --output json 2>/dev/null)" || die "базу створено, але не вдалося перевірити її тариф — перевірте вручну в консолі"

echo "$CREATED" | grep -q '"free": true' \
  || die "УВАГА: створена база НЕ є Always Free. Негайно перевірте в консолі OCI та видаліть, якщо вона платна."

echo
echo "Готово, база безкоштовна. Параметри:"
echo "$CREATED"
echo
echo "Далі:  ./03-download-wallet.sh"
