-- Компілює поточний робочий файл учасника; таблиці й фікстури не змінює.
-- CREATE PACKAGE BODY — DDL, тому використовуйте окреме підключення.
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set serveroutput on
set define off
@@_assert-lab.sql
@@settlement.pkb.sql
@@_assert-compiled.sql
prompt COMPILE_OK: поточне тіло скомпільовано; далі виконайте verify.sql.
exit success rollback
