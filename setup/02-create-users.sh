#!/usr/bin/env bash
#
# Створює схеми учасників і тренера з паролів, згенерованих у 00.
#
# Запуск:  ./02-create-users.sh
#
# Передумови:
#   ./00-generate-secrets.sh   (паролі + users.txt)
#   ./03-download-wallet.sh    (wallet)
#   sample-схеми HR і CO встановлені
#
# ---------------------------------------------------------------------------
# ВАЖЛИВО, перевірено практикою на Autonomous Database:
#
# 1. DDL нижче навмисно ПЛОСКИЙ, без PL/SQL-обгортки. Привілеї, видані
#    через роль (а CREATE USER в ADMIN на ADB саме такий), НЕ діють
#    усередині анонімного блоку. Обгортка дала б ORA-01031.
#
# 2. Схема SH на ADB вбудована (ORACLE_MAINTAINED=Y, LOCKED). Гранти на неї
#    неможливі (ORA-01031) і не потрібні — вона й так читається всіма.
#    Тому роль training_read покриває лише HR і CO.
# ---------------------------------------------------------------------------

set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

command -v sql >/dev/null || die "SQLcl (sql) не знайдено в PATH"
[[ -s "$WALLET_FILE" ]] || die "немає wallet: $WALLET_FILE. Запустіть 03-download-wallet.sh"

ADMIN_PWD="$(need_secret adb-admin-password)"
USERS_FILE="$SECRETS_DIR/users.txt"
[[ -s "$USERS_FILE" ]] || die "немає $USERS_FILE. Запустіть 00-generate-secrets.sh"

CONN="ADMIN/$ADMIN_PWD@$DB_SERVICE"
GEN="$(mktemp)"; trap 'rm -f "$GEN" "$GEN.grants"' EXIT

# --- 1. Гранти на HR і CO — генеруємо з живого словника -------------------

log "Отримуємо перелік таблиць HR і CO..."
sql -S -cloudconfig "$WALLET_FILE" "$CONN" <<'EOF' > "$GEN.grants" 2>&1
set feedback off pagesize 0 heading off trimspool on verify off
select 'grant select on "'||owner||'"."'||table_name||'" to training_read;'
  from all_tables where owner in ('HR','CO') order by owner, table_name;
exit
EOF

GRANT_COUNT="$(grep -c '^grant select' "$GEN.grants" || true)"
[[ "$GRANT_COUNT" -gt 0 ]] \
  || die "не знайдено таблиць HR/CO. Спершу встановіть sample-схеми (див. SETUP.md)"
log "Знайдено таблиць: $GRANT_COUNT"

# --- 2. Складаємо плоский скрипт -----------------------------------------

{
  echo 'whenever sqlerror continue none'
  echo 'set feedback off'
  echo 'create role training_read;'   # ORA-01921 якщо існує — це нормально
  grep '^grant select' "$GEN.grants"
  while IFS=: read -r u p; do
    [[ -n "$u" ]] || continue
    echo "create user $u identified by \"$p\" quota 1G on DATA;"
    echo "grant connect, resource to $u;"
    echo "grant training_read to $u;"
    echo "grant select_catalog_role to $u;"   # для демо аудиту через V\$SQL
  done < "$USERS_FILE"
  echo 'exit'
} > "$GEN"

log "Виконуємо ($(wc -l < "$GEN") рядків)..."
sql -S -cloudconfig "$WALLET_FILE" "$CONN" "@$GEN" > "$GEN.log" 2>&1 || true

# ORA-01921 (роль існує) і ORA-01920 (користувач існує) — очікувані при повторі
UNEXPECTED="$(grep -oE 'ORA-[0-9]+' "$GEN.log" | sort -u | grep -vE 'ORA-01921|ORA-01920' || true)"
if [[ -n "$UNEXPECTED" ]]; then
  warn "неочікувані помилки: $(echo "$UNEXPECTED" | tr '\n' ' ')"
fi
rm -f "$GEN.log"

# --- 3. Перевірка ---------------------------------------------------------

echo
echo "Перевірка:"
sql -S -cloudconfig "$WALLET_FILE" "$CONN" <<EOF
set feedback off pagesize 50
select username, account_status from dba_users
 where username in ($(printf "'%s'," "${TRAINING_USERS[@]}" | sed 's/,$//')) order by 1;
select owner, count(*) as granted_tables from dba_tab_privs
 where grantee='TRAINING_READ' group by owner order by 1;
exit
EOF

echo
echo "Очікуємо ${#TRAINING_USERS[@]} користувачів OPEN і гранти на HR та CO."
echo "SH у переліку грантів НЕ буде — і це правильно (див. коментар угорі)."
