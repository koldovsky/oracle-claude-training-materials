@@_guard-owner.sql

declare
  l_count pls_integer;
begin
  select count(*) into l_count
    from user_tab_comments
   where table_name in ('S2_ORDERS', 'S2_ORDER_ITEMS')
     and table_type = 'TABLE'
     and comments = 'ACORDBANK_SESSION_2_V1';
  if l_count <> 2 then
    raise_application_error(-20991,
      'Не знайдено обидві позначені таблиці лабораторії. Спочатку виконайте install.sql.');
  end if;

  select count(*) into l_count
    from user_source
   where name = 'S2_SETTLEMENT' and type = 'PACKAGE'
     and instr(text, 'ACORDBANK_SESSION_2_V1') > 0;
  if l_count <> 1 then
    raise_application_error(-20992,
      'S2_SETTLEMENT не має очікуваної позначки лабораторії. Автоматичну заміну зупинено.');
  end if;
end;
/
