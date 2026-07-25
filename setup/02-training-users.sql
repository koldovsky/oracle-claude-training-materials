-- Схеми для навчання: 5 учасників + окрема демо-схема тренера.
-- Виконувати від імені ADMIN на навчальній ADB:
--
--   sql -cloudconfig wallet.zip ADMIN/<pwd>@acordtrain_low @02-training-users.sql
--
-- ПЕРЕД ЗАПУСКОМ замініть паролі в секції 3.
-- Вимоги: 12-30 символів, мін. 1 велика, 1 мала, 1 цифра, без символу "
--
-- ---------------------------------------------------------------------------
-- ВАЖЛИВО, перевірено практикою на Autonomous Database:
--
-- 1. DDL тут навмисно ПЛОСКИЙ, без PL/SQL-обгортки.
--    Привілеї, видані через роль (а CREATE USER у ADMIN на ADB саме такий),
--    НЕ діють усередині анонімного PL/SQL-блоку. Спроба загорнути
--    CREATE USER у BEGIN...END дає ORA-01031: insufficient privileges.
--
-- 2. Схема SH на ADB — вбудована, ORACLE_MAINTAINED=Y, LOCKED.
--    Її НЕ треба встановлювати: вона вже є і читається всіма користувачами.
--    Видати на неї грант неможливо (ORA-01031) — і не потрібно.
--    Встановлюємо лише HR і CO.
-- ---------------------------------------------------------------------------

whenever sqlerror continue none
set feedback off

-- ---------------------------------------------------------------
-- 1. Роль для читання встановлених sample-схем (HR, CO).
--    Учасники отримують їх ТІЛЬКИ на читання.
-- ---------------------------------------------------------------

create role training_read;
-- ORA-01921, якщо роль уже існує — це нормально, продовжуємо.

-- ---------------------------------------------------------------
-- 2. Гранти на всі таблиці HR і CO.
--    Генеруємо динамічно, бо перелік таблиць може змінюватись.
-- ---------------------------------------------------------------

set pagesize 0 heading off trimspool on verify off termout off
spool _grants_generated.sql
select 'grant select on "' || owner || '"."' || table_name || '" to training_read;'
  from all_tables
 where owner in ('HR', 'CO')
 order by owner, table_name;
spool off
set termout on

@_grants_generated.sql

-- ---------------------------------------------------------------
-- 3. Користувачі: 5 учасників + тренер.
--
--    TRAINEE1..5 — по одній ізольованій схемі на людину
--    TRAINER     — демо-схема, щоб показ на занятті не зачіпав учасників
--
--    SELECT_CATALOG_ROLE потрібна для демо аудиту (доступ до V$SQL).
-- ---------------------------------------------------------------

create user TRAINEE1 identified by "Change1Me2026Now" quota 1G on DATA;
grant connect, resource to TRAINEE1;
grant training_read to TRAINEE1;
grant select_catalog_role to TRAINEE1;

create user TRAINEE2 identified by "Change2Me2026Now" quota 1G on DATA;
grant connect, resource to TRAINEE2;
grant training_read to TRAINEE2;
grant select_catalog_role to TRAINEE2;

create user TRAINEE3 identified by "Change3Me2026Now" quota 1G on DATA;
grant connect, resource to TRAINEE3;
grant training_read to TRAINEE3;
grant select_catalog_role to TRAINEE3;

create user TRAINEE4 identified by "Change4Me2026Now" quota 1G on DATA;
grant connect, resource to TRAINEE4;
grant training_read to TRAINEE4;
grant select_catalog_role to TRAINEE4;

create user TRAINEE5 identified by "Change5Me2026Now" quota 1G on DATA;
grant connect, resource to TRAINEE5;
grant training_read to TRAINEE5;
grant select_catalog_role to TRAINEE5;

create user TRAINER identified by "Change6Me2026Now" quota 1G on DATA;
grant connect, resource to TRAINER;
grant training_read to TRAINER;
grant select_catalog_role to TRAINER;

-- ---------------------------------------------------------------
-- 4. Перевірка
-- ---------------------------------------------------------------

set feedback on pagesize 50 heading on

select username, account_status
  from dba_users
 where username like 'TRAINEE%' or username = 'TRAINER'
 order by username;

select owner, count(*) as granted_tables
  from dba_tab_privs
 where grantee = 'TRAINING_READ'
 group by owner
 order by owner;

-- Очікуємо: 6 користувачів OPEN, гранти на HR і CO.
-- SH у цьому переліку НЕ буде — і це правильно (див. примітку вгорі).

-- Підключення учасника. Сервіс _low обмежує паралелізм одного запиту
-- й дає більше одночасних сесій — саме те, що треба для кількох людей:
--   conn -save train -savepwd TRAINEE1/<pwd>@acordtrain_low
