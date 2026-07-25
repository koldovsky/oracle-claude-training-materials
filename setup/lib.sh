#!/usr/bin/env bash
#
# Спільні налаштування для всіх скриптів розгортання.
# Підключається як:  . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
#
# ЄДИНЕ місце, де визначається, де лежать секрети і wallet.
# Раніше кожен скрипт вирішував це сам — і вони розійшлися:
# одні писали в setup/.secrets, інші читали з ~/.secrets, а інструкція
# посилалася на третій варіант. Через це середовище не відтворювалося
# за документацією, хоча кожен скрипт окремо працював.

# Перевизначається змінною оточення, якщо треба інше розташування
SECRETS_DIR="${ACORDBANK_SECRETS_DIR:-$HOME/.acordbank/secrets}"
WALLET_FILE="$SECRETS_DIR/wallet.zip"

DB_NAME="${DB_NAME:-ACORDTRAIN}"
DB_SERVICE="${DB_SERVICE:-${DB_NAME,,}_low}"

# Перелік облікових записів, які створюємо
TRAINING_USERS=(TRAINEE1 TRAINEE2 TRAINEE3 TRAINEE4 TRAINEE5 TRAINER)

log()  { printf '  %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*" >&2; }
die()  { printf 'ПОМИЛКА: %s\n' "$*" >&2; exit 1; }

# Читає секрет або зупиняє скрипт. Значення НЕ виводиться.
need_secret() {
  local f="$SECRETS_DIR/$1"
  [[ -s "$f" ]] || die "немає секрету '$1' у $SECRETS_DIR. Запустіть 00-generate-secrets.sh"
  cat "$f"
}

# Визначає compartment: явно заданий -> $OCI_TENANCY (Cloud Shell) -> ~/.oci/config
resolve_compartment() {
  if [[ -n "${COMPARTMENT_OCID:-}" ]]; then
    printf '%s' "$COMPARTMENT_OCID"; return
  fi
  if [[ -n "${OCI_TENANCY:-}" ]]; then
    printf '%s' "$OCI_TENANCY"; return
  fi
  if [[ -f "$HOME/.oci/config" ]]; then
    grep -E '^tenancy' "$HOME/.oci/config" | head -1 | cut -d= -f2 | tr -d ' '
    return
  fi
  die "не вдалося визначити compartment. Задайте COMPARTMENT_OCID вручну"
}
