-- Видаляє лише власні об'єкти цієї лабораторії після перевірки позначок.
-- DDL фіксує транзакцію: використовуйте окреме підключення.
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set serveroutput on
set define off
@@_guard-owner.sql

declare
  l_count pls_integer;
  l_marked pls_integer;
begin
  -- Спочатку перевіряємо ВСІ цілі; до завершення перевірки нічого не видаляємо.
  for t in (
    select object_name, object_type from user_objects
     where object_name in ('S2_ORDERS', 'S2_ORDER_ITEMS', 'S2_SETTLEMENT')
  ) loop
    if t.object_name in ('S2_ORDERS', 'S2_ORDER_ITEMS') and t.object_type = 'TABLE' then
      select count(*) into l_marked from user_tab_comments
       where table_name = t.object_name and comments = 'ACORDBANK_SESSION_2_V1';
    elsif t.object_name = 'S2_SETTLEMENT' and t.object_type in ('PACKAGE', 'PACKAGE BODY') then
      select count(*) into l_marked from user_source
       where name = 'S2_SETTLEMENT' and type = 'PACKAGE'
         and instr(text, 'ACORDBANK_SESSION_2_V1') > 0;
    else
      l_marked := 0;
    end if;
    if l_marked <> 1 then
      raise_application_error(-20997,
        'Непізнаний об''єкт ' || t.object_name || ': автоматичне видалення зупинено.');
    end if;
  end loop;

  select count(*) into l_count from user_objects
   where object_name = 'S2_SETTLEMENT' and object_type = 'PACKAGE';
  if l_count = 1 then execute immediate 'drop package s2_settlement'; end if;
  select count(*) into l_count from user_tables where table_name = 'S2_ORDER_ITEMS';
  if l_count = 1 then execute immediate 'drop table s2_order_items purge'; end if;
  select count(*) into l_count from user_tables where table_name = 'S2_ORDERS';
  if l_count = 1 then execute immediate 'drop table s2_orders purge'; end if;
end;
/
prompt CLEANUP_OK: позначені об'єкти лабораторії видалено; інші об'єкти не змінювались.
exit success rollback
