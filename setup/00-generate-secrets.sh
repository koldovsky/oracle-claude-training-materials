#!/usr/bin/env bash
#
# Генерує ВСІ облікові дані навчального середовища.
#
# Запуск:  ./00-generate-secrets.sh
#
# Створює:
#   adb-admin-password      пароль ADMIN навчальної БД
#   wallet-password         пароль архіву wallet
#   sample-schema-password  пароль власників схем HR і CO
#   users.txt               логін:пароль для 5 учасників і тренера
#
# Ідемпотентний: наявні значення не перезаписуються.
# Жоден пароль не виводиться на екран.

set -euo pipefail
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR" 2>/dev/null || true

# Вимоги Oracle до пароля: 12-30 символів, мін. 1 велика, 1 мала, 1 цифра,
# без символу " і без підрядка "admin".
# Алфавіт лише [A-Za-z0-9] — безпечно для shell, TNS і не потребує екранування.
generate_password() {
  local raw pwd
  while true; do
    # Читаємо фіксований блок і лише потім фільтруємо: інакше `head` закриє
    # пайп раніше за `tr`, той отримає SIGPIPE і скрипт впаде під pipefail.
    raw="$(head -c 512 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
    pwd="${raw:0:20}"
    [[ ${#pwd} -eq 20 ]]        || continue
    [[ "$pwd" == *[A-Z]* ]]     || continue
    [[ "$pwd" == *[a-z]* ]]     || continue
    [[ "$pwd" == *[0-9]* ]]     || continue
    [[ "${pwd,,}" != *admin* ]] || continue
    printf '%s' "$pwd"
    return
  done
}

write_secret() {
  local name="$1" file="$SECRETS_DIR/$1" value
  # -s, а не -f: порожній файл вважаємо відсутнім. Інакше збій під час
  # генерації лишить файл на 0 байт, який виглядає як «вже готовий».
  if [[ -s "$file" ]]; then
    log "$name — вже існує, лишаємо"
    return
  fi
  # Спочатку у змінну, потім у файл: так файл або коректний, або його немає.
  value="$(generate_password)"
  printf '%s' "$value" > "$file"
  chmod 600 "$file" 2>/dev/null || true
  log "$name — згенеровано"
}

echo "Каталог секретів: $SECRETS_DIR"

write_secret adb-admin-password
write_secret wallet-password
write_secret sample-schema-password

# --- облікові записи учасників -------------------------------------------

USERS_FILE="$SECRETS_DIR/users.txt"
touch "$USERS_FILE"; chmod 600 "$USERS_FILE" 2>/dev/null || true

for u in "${TRAINING_USERS[@]}"; do
  if grep -q "^$u:" "$USERS_FILE" 2>/dev/null; then
    log "$u — вже існує, лишаємо"
  else
    printf '%s:%s\n' "$u" "$(generate_password)" >> "$USERS_FILE"
    log "$u — згенеровано"
  fi
done

echo
echo "Готово. Паролі на екран не виводяться."
echo "Облікові записи: $(cut -d: -f1 "$USERS_FILE" | tr '\n' ' ')"
echo
echo "УВАГА: у Windows chmod не змінює реальні NTFS-права. Якщо машина спільна —"
echo "перенесіть каталог у захищене місце або видаліть після налаштування."
