#!/usr/bin/env bash
#
# Генерує паролі для навчальної БД і зберігає їх у setup/.secrets/.
# Паролі створюються локально й нікуди не передаються.
#
# Запуск:  ./00-generate-secrets.sh
#
# Ідемпотентний: якщо файл уже існує, пароль НЕ перезаписується.
# Щоб перегенерувати — видаліть відповідний файл вручну.

set -euo pipefail

SECRETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.secrets"
mkdir -p "$SECRETS_DIR"

# Вимоги Oracle до пароля ADMIN:
#   12-30 символів, мін. 1 велика літера, 1 мала, 1 цифра,
#   без символу " і без підрядка "admin".
# Використовуємо лише [A-Za-z0-9] — так пароль безпечний для shell,
# TNS-рядків і не потребує екранування.
generate_password() {
  local raw pwd
  while true; do
    # Читаємо фіксований блок і лише потім фільтруємо: інакше `head` закриває
    # пайп раніше за `tr`, той отримує SIGPIPE, і скрипт падає під `pipefail`.
    raw="$(head -c 512 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9')"
    pwd="${raw:0:20}"

    [[ ${#pwd} -eq 20 ]]                  || continue
    [[ "$pwd" == *[A-Z]* ]]               || continue
    [[ "$pwd" == *[a-z]* ]]               || continue
    [[ "$pwd" == *[0-9]* ]]               || continue
    [[ "${pwd,,}" != *admin* ]]           || continue
    printf '%s' "$pwd"
    return
  done
}

write_secret() {
  local name="$1" file="$SECRETS_DIR/$1" value

  # -s, а не -f: порожній файл вважаємо відсутнім. Інакше збій під час
  # генерації лишає файл на 0 байт, який виглядає як «вже готовий».
  if [[ -s "$file" ]]; then
    echo "  $name — вже існує, лишаємо без змін"
    return
  fi

  # Спочатку генеруємо у змінну й лише потім пишемо: так файл або
  # коректний, або його немає взагалі.
  value="$(generate_password)"
  printf '%s' "$value" > "$file"
  chmod 600 "$file" 2>/dev/null || true
  echo "  $name — згенеровано"
}

echo "Каталог секретів: $SECRETS_DIR"
write_secret adb-admin-password
write_secret wallet-password

echo
echo "Готово. Паролі на екран не виводяться."
echo "Переглянути за потреби:  cat '$SECRETS_DIR/adb-admin-password'"
echo
echo "УВАГА: у Windows chmod не змінює реальні NTFS-права. Якщо машина спільна —"
echo "перенесіть каталог .secrets у захищене місце або видаліть після налаштування."
