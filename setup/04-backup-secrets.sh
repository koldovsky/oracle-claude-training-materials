#!/usr/bin/env bash
#
# Збирає всі доступи навчального середовища в ОДИН зашифрований файл.
#
# Запуск (у Cloud Shell, де лежить ~/.secrets):
#   ./04-backup-secrets.sh
#
# Скрипт запитає парольну фразу — її вводите ВИ, вона нікуди не записується.
# Запам'ятайте або збережіть її в менеджері паролів: без неї архів не відкрити.
#
# Результат: ~/acordbank-secrets.gpg — завантажте через Menu -> Download.
#
# Відкрити пізніше (Git Bash / Linux / macOS):
#   gpg -d acordbank-secrets.gpg | tar xzf - -C ./restored
#
# Жоден пароль на екран не виводиться.

set -euo pipefail

SECRETS_DIR="$HOME/.secrets"
WALLET="$HOME/wallet.zip"
OUT="$HOME/acordbank-secrets.gpg"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
chmod 700 "$STAGE"

[[ -d "$SECRETS_DIR" ]] || { echo "ПОМИЛКА: немає $SECRETS_DIR" >&2; exit 1; }

read_secret() {  # тихо читає файл; порожньо, якщо його немає
  [[ -s "$SECRETS_DIR/$1" ]] && cat "$SECRETS_DIR/$1" || echo "(немає)"
}

# --- OCI / БД: витягуємо з живого середовища, а не з пам'яті ---
ADB_OCID="$(oci db autonomous-database list \
  --compartment-id "${OCI_TENANCY:-}" \
  --query "data[?\"db-name\"=='ACORDTRAIN'] | [0].id" --raw-output 2>/dev/null || echo '(не визначено)')"

{
  echo "==============================================================="
  echo " AcordBank — навчальне середовище Claude Code + Oracle"
  echo " Резервна копія доступів"
  echo " Створено: $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "==============================================================="
  echo
  echo "--- Oracle Cloud ---"
  echo "Tenancy OCID : ${OCI_TENANCY:-(не визначено)}"
  echo "Регіон       : ${OCI_REGION:-eu-frankfurt-1}"
  echo "ADB OCID     : $ADB_OCID"
  echo "Ім'я БД      : ACORDTRAIN"
  echo "Версія       : Oracle 19.32.0.1.0, Always Free"
  echo "Сервіси      : acordtrain_low / _medium / _high"
  echo "               (для навчання використовуємо _low)"
  echo
  echo "--- Паролі БД ---"
  echo "ADMIN                : $(read_secret adb-admin-password)"
  echo "Пароль wallet        : $(read_secret wallet-password)"
  echo "Власники HR/CO схем  : $(read_secret sample-schema-password)"
  echo
  echo "--- Користувачі (логін:пароль) ---"
  if [[ -s "$SECRETS_DIR/users.txt" ]]; then cat "$SECRETS_DIR/users.txt"; else echo "(немає users.txt)"; fi
  echo
  echo "TRAINEE1..5 — учасники, кожен у власній схемі"
  echo "TRAINER     — демо-схема тренера"
  echo "Усі мають: CONNECT, RESOURCE, training_read (читання HR/CO),"
  echo "           SELECT_CATALOG_ROLE (для демо аудиту через V\$SQL)"
  echo
  echo "--- GitHub ---"
  echo "Репозиторій : https://github.com/koldovsky/acordbank-oracle-training"
  echo
  echo "Секрети рівня РЕПОЗИТОРІЮ (спільні):"
  echo "  ADB_WALLET_B64  = base64 -w0 wallet.zip"
  echo "  ADB_SERVICE     = acordtrain_low"
  echo
  echo "Секрети рівня КОРИСТУВАЧА (кожен свої, scope = цей репозиторій):"
  echo "  ADB_USER        = TRAINEE1 / TRAINER / ..."
  echo "  ADB_PASSWORD    = відповідний пароль вище"
  echo
  echo "--- Що робити, якщо щось загублено ---"
  echo "Пароль ADMIN     : скидається в консолі OCI, ADB -> More actions -> Administrator password"
  echo "Wallet           : перегенерується — setup/03-download-wallet.sh"
  echo "Паролі учасників : скидаються від ADMIN через ALTER USER ... IDENTIFIED BY"
  echo "Тобто нічого тут не є непоправним — це копія для зручності, не єдина точка відмови."
} > "$STAGE/ДОСТУПИ.txt"

# --- wallet ---
if [[ -f "$WALLET" ]]; then
  cp "$WALLET" "$STAGE/wallet.zip"
else
  echo "(wallet.zip не знайдено — перегенеруйте через 03-download-wallet.sh)" > "$STAGE/wallet-ВІДСУТНІЙ.txt"
fi

echo "Зібрано: $(ls "$STAGE" | tr '\n' ' ')"
echo
echo "УВАГА: у Cloud Shell немає pinentry, тому gpg працює в режимі loopback"
echo "і питає фразу ОДИН раз, без підтвердження. Друкарська помилка мовчки"
echo "стане паролем. Тому нижче — обов'язкова перевірка розшифруванням."
echo

rm -f "$OUT"
tar czf - -C "$STAGE" . \
  | gpg --symmetric --pinentry-mode loopback \
        --cipher-algo AES256 --s2k-digest-algo SHA512 -o "$OUT"

chmod 600 "$OUT"
echo
echo "Зашифровано: $OUT ($(stat -c%s "$OUT") байт)"
echo

# --- перевірка ---------------------------------------------------------
# Скидання кешу агента тут КРИТИЧНЕ. Без нього gpg візьме фразу з кешу,
# розшифрує успішно й покаже "все добре" — навіть якщо ви ввели не те,
# що думаєте. Перевірка без цього рядка не перевіряє нічого.
gpgconf --kill gpg-agent 2>/dev/null || true
sleep 1

echo "Перевірка: введіть ТУ САМУ фразу ще раз."
if gpg -d --pinentry-mode loopback "$OUT" 2>/dev/null | tar tzf - > /dev/null; then
  echo
  echo "OK — архів відкривається цією фразою."
  echo "Завантажте через Menu -> Download, ім'я файлу: acordbank-secrets.gpg"
  echo "Відкрити пізніше:  gpg -d acordbank-secrets.gpg | tar xzf - -C ./restored"
else
  echo
  echo "ПОМИЛКА: архів не відкривається введеною фразою." >&2
  echo "Файл $OUT непридатний — видаліть його і запустіть скрипт заново." >&2
  exit 1
fi
