# Розгортання навчального середовища

Покрокова інструкція. Розрахована на те, що виконувати її буде людина,
яка не брала участі в первинному налаштуванні.

Порядок має значення: кожен крок спирається на попередній.

---

## Частина A. Тренер, один раз

### A1. База даних

Потрібен OCI CLI (у **Cloud Shell** він уже є й автентифікований — це найпростіший шлях).

```bash
./setup/00-generate-secrets.sh    # паролі ADMIN і wallet, локально, на екран не виводяться
./setup/01-create-adb.sh          # Always Free ADB; зупиниться, якщо ліміт вичерпано
./setup/03-download-wallet.sh     # wallet.zip
```

Скрипт `01` **перевіряє кількість наявних Always Free баз перед створенням**.
Це не формальність: при вичерпаному ліміті прапорець `--is-free-tier` не дає
помилки, а мовчки створює **платну** базу.

### A2. Sample-схеми

```bash
curl -sL -o s.zip https://github.com/oracle-samples/db-sample-schemas/archive/refs/tags/v23.1.zip
unzip -q s.zip && mv db-sample-schemas-23.1 db-sample-schemas && rm s.zip
```

Ставимо **лише HR і CO**:

```bash
cd db-sample-schemas/human_resources
printf '%s\nDATA\nYES\n' "$(cat ~/.secrets/sample-schema-password)" \
  | sql -S -cloudconfig ~/wallet.zip ADMIN/"$(cat ~/.secrets/adb-admin-password)"@acordtrain_low @hr_install.sql
```

Те саме для `customer_orders/co_install.sql`.

> **SH встановлювати не треба.** На Autonomous Database вона вже є —
> `ORACLE_MAINTAINED=Y`, `LOCKED`. Спроба інсталяції завершиться помилкою,
> видати на неї грант теж неможливо (`ORA-01031`) — і не потрібно: вона
> читається всіма користувачами автоматично. Це не проблема, а зручність:
> зіпсувати її не може ніхто.

> Інсталятори **не запускати через `nohup`** — вони питають пароль
> маскованим вводом, а без TTY це ламається.

### A3. Схеми учасників

```bash
sql -cloudconfig ~/wallet.zip ADMIN/<pwd>@acordtrain_low @setup/02-training-users.sql
```

Перед запуском **замініть паролі** в секції 3 скрипта.

> DDL у скрипті навмисно **плоский, без PL/SQL-обгортки**. Привілеї, видані
> через роль (а `CREATE USER` в ADMIN на ADB саме такий), не діють усередині
> анонімного блоку — обгортка дала б `ORA-01031`.

Перевірка: 6 користувачів `OPEN`, гранти на HR і CO. SH у списку грантів
не буде — так і має бути.

### A4. Секрети GitHub

**Рівень репозиторію** (Settings → Secrets and variables → Codespaces):

| Секрет | Значення |
|---|---|
| `ADB_WALLET_B64` | `base64 -w0 wallet.zip` |
| `ADB_SERVICE` | `acordtrain_low` |

Персонального сюди **не класти**. Якщо покласти логін і пароль — усі учасники
підключаться під одним записом в одну схему, і ізоляції не буде.

### A5. Резервна копія доступів

```bash
./setup/04-backup-secrets.sh
```

Питає парольну фразу **один раз без підтвердження** (у Cloud Shell немає
pinentry). Тому скрипт одразу перевіряє архів розшифруванням — попередньо
скидаючи кеш gpg-agent, інакше перевірка пройшла б на кеші й нічого б не довела.

Завантажити: **Menu → Download**, `acordbank-secrets.gpg`.
Відкрити: `gpg -d acordbank-secrets.gpg | tar xzf - -C ./restored`

---

## Частина B. Кожен учасник

### B1. Свої секрети

**Ваші GitHub Settings → Codespaces → Secrets → New secret**,
у полі **Repository access** оберіть цей репозиторій:

| Секрет | Значення |
|---|---|
| `ADB_USER` | ваш логін (`TRAINEE1`…) — видає тренер |
| `ADB_PASSWORD` | ваш пароль — видає тренер |

Зробити **до** створення Codespace.

### B2. Codespace

**Code → Codespaces → Create codespace on main.** Перша збірка ~3-5 хв.

### B3. Вхід у Claude Code

```bash
claude
```

Браузер поверне код на `http://localhost:<порт>` — **сторінка не відкриється,
це нормально**: у Codespaces цей порт до контейнера не прокидається.

З адреси, на якій браузер спіткнувся, візьміть `code` і `state` та вставте
в термінал на запит `Paste code here if prompted >`, з'єднавши решіткою:

```
<code>#<state>
```

Код живе кілька хвилин. Не встигли — `/login` заново.

### B4. Перевірка

Запитайте у Claude:

> покажи, скільки рядків у HR.EMPLOYEES, CO.ORDERS і SH.SALES

Claude попросить дозвіл на MCP-сервер `sqlcl` — підтвердіть. Очікувані числа:

| Таблиця | Рядків |
|---|---|
| HR.EMPLOYEES | 107 |
| CO.ORDERS | 1 950 |
| SH.SALES | 918 843 |

Збіглося — середовище готове.

---

## Якщо щось не працює

| Симптом | Причина і що робити |
|---|---|
| `Could not find or load main class ...SqlCli` | Права на файли SQLcl. Виглядає як зламаний classpath, насправді jar-и недоступні на читання. `sudo chmod -R a+rX /opt/sqlcl`. У Dockerfile це вже враховано |
| `Not logged in` одразу після входу, `Transcript writes are failing (EACCES)` | Том `~/.claude` належить root. `sudo chown -R vscode:vscode ~/.claude`. У `postCreateCommand` це вже враховано |
| `post-create.sh` пише, що бракує `ADB_USER` | Не додані секрети **рівня користувача** (крок B1). Після додавання — перестворити Codespace |
| Підключення до БД не відповідає | Перевірте, що ADB не зупинена: Always Free зупиняється після тривалої бездіяльності. Запустіть у консолі OCI |
| `ORA-00942` на чужу схему | Так і має бути — це ізоляція учасників, а не помилка |
| Після **Full Rebuild** Claude Code просить налаштування з нуля | Очікувано: Full Rebuild скидає том `~/.claude` разом із авторизацією. Звичайний **Rebuild** її зберігає. Якщо мета — лише підхопити зміни в `devcontainer.json`, беріть звичайний Rebuild |

---

## Перевірка після змін у конфігурації середовища

Якщо правили `Dockerfile` чи `devcontainer.json` — перевіряйте **Full Rebuild**,
а не ручними правками в контейнері. Полагоджений руками контейнер нічого не
доводить: учасник отримає зібраний образ, а не ваш виправлений.

Після збірки все має працювати без єдиної ручної команди:

```bash
sql -V                                    # Release 26.x Production
stat -c '%U:%G' ~/.claude                 # vscode:vscode
ls -l ~/adb-wallet/wallet.zip             # ~25 КБ
sql -S /nolog <<< $'connmgr list\nexit'   # має бути train
sql -S -name train <<< $'select count(*) from hr.employees;\nexit'   # 107
```

---

## Перед кожною сесією

- [ ] ADB запущена (не `STOPPED`)
- [ ] Codespace кожного учасника створюється й проходить перевірку B4
- [ ] Схеми учасників на місці
