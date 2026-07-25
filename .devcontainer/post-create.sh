#!/usr/bin/env bash
#
# Готує підключення до навчальної Oracle Autonomous Database.
# Запускається автоматично при створенні Codespace.
#
# Потрібні Codespaces secrets (Settings → Secrets and variables → Codespaces):
#   ADB_WALLET_B64  — wallet.zip у base64  (base64 -w0 wallet.zip)
#   ADB_USER        — напр. TRAINEE1
#   ADB_PASSWORD    — пароль цього користувача
#   ADB_SERVICE     — напр. acordtrain_low
#
# Секрети потрапляють у контейнер як змінні оточення. На диск лягає лише
# розпакований wallet — у git він не потрапляє (див. .gitignore).

set -euo pipefail

WALLET_DIR="$HOME/adb-wallet"
CONN_NAME="${ADB_CONN_NAME:-train}"

log()  { printf '  %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*"; }

echo "=== Підключення до навчальної ADB ==="

if [[ -z "${ADB_WALLET_B64:-}" ]]; then
  warn "Секрет ADB_WALLET_B64 не заданий — пропускаємо налаштування БД."
  warn "Claude Code працюватиме, але без доступу до бази."
  warn "Додайте секрети й перестворіть Codespace (або запустіть цей скрипт вручну)."
  exit 0
fi

# --- wallet ---------------------------------------------------------------

mkdir -p "$WALLET_DIR"
chmod 700 "$WALLET_DIR"
printf '%s' "$ADB_WALLET_B64" | base64 -d > "$WALLET_DIR/wallet.zip"

if ! unzip -tq "$WALLET_DIR/wallet.zip" >/dev/null 2>&1; then
  echo "ПОМИЛКА: після декодування ADB_WALLET_B64 це не коректний zip." >&2
  echo "Перевірте, що секрет створено як: base64 -w0 wallet.zip" >&2
  rm -f "$WALLET_DIR/wallet.zip"
  exit 1
fi
chmod 600 "$WALLET_DIR/wallet.zip"
log "wallet отримано ($(stat -c%s "$WALLET_DIR/wallet.zip") байт)"

# --- збережене з'єднання --------------------------------------------------

if [[ -z "${ADB_USER:-}" || -z "${ADB_PASSWORD:-}" ]]; then
  warn "Не задані ваші особисті секрети ADB_USER / ADB_PASSWORD."
  warn "Додайте їх у GitHub Settings -> Codespaces -> Secrets,"
  warn "у полі Repository access оберіть цей репозиторій, і перестворіть Codespace."
  warn "Це секрети рівня КОРИСТУВАЧА, не репозиторію — саме вони дають кожному власну схему."
  exit 0
fi

if [[ -z "${ADB_SERVICE:-}" ]]; then
  warn "Не заданий ADB_SERVICE (секрет рівня репозиторію) — зверніться до тренера."
  exit 0
fi

# -savepwd обов'язковий: без збереженого пароля MCP-сервер не зможе
# під'єднатися самостійно, коли Claude Code його викличе.
sql -S /nolog > /tmp/_conn_setup.log 2>&1 <<EOF || true
set cloudconfig $WALLET_DIR/wallet.zip
connect -save $CONN_NAME -savepwd $ADB_USER/$ADB_PASSWORD@$ADB_SERVICE
exit
EOF

if grep -qiE 'ORA-|error' /tmp/_conn_setup.log; then
  warn "Не вдалося зберегти з'єднання. Деталі (без пароля):"
  grep -oE 'ORA-[0-9]+.*|SP2-[0-9]+.*' /tmp/_conn_setup.log | head -3 || true
  rm -f /tmp/_conn_setup.log
  exit 1
fi
rm -f /tmp/_conn_setup.log
log "збережено з'єднання '$CONN_NAME' для користувача $ADB_USER"

# --- перевірка ------------------------------------------------------------

sql -S -name "$CONN_NAME" > /tmp/_conn_test.log 2>&1 <<'EOF' || true
set feedback off
select 'CONNECT_OK' as st from dual;
exit
EOF

if grep -q CONNECT_OK /tmp/_conn_test.log; then
  log "перевірка підключення: OK"
else
  warn "перевірка підключення НЕ пройшла:"
  grep -oE 'ORA-[0-9]+.*|SP2-[0-9]+.*|IO Error.*' /tmp/_conn_test.log | head -3 || true
fi
rm -f /tmp/_conn_test.log

echo "=== Готово ==="
echo
echo "Claude Code бачить базу через MCP-сервер SQLcl (.mcp.json)."
echo "Перевірити: запустіть 'claude' і попросіть показати список таблиць HR."
