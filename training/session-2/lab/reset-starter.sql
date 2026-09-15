-- Видаляє лише дані двох позначених таблиць лабораторії та повертає початкове тіло.
-- Зберігайте свій SQL у git; цей крок фіксує транзакцію. Окреме підключення.
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set serveroutput on
set define off
@@_assert-lab.sql

delete from s2_order_items;
delete from s2_orders;
@@_seed.sql
@@settlement-starter.pkb.sql
@@_assert-compiled.sql
prompt RESET_OK: фікстури та початкове тіло відновлено.
exit success rollback
