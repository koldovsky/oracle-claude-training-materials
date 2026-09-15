-- Запуск із кореня репозиторію: @training/session-2/lab/install.sql
-- DDL і заповнення фікстур фіксують транзакцію: використовуйте окреме підключення.
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set serveroutput on
set define off
@@_guard-owner.sql

declare
  l_count pls_integer;
begin
  select count(*) into l_count
    from (
      select object_name as name from user_objects where object_name like 'S2\_%' escape '\'
      union all
      select constraint_name from user_constraints where constraint_name like 'S2\_%' escape '\'
    );
  if l_count <> 0 then
    raise_application_error(-20994,
      'У схемі вже є об''єкти S2_. Install нічого не замінює. Для власної лабораторії є reset-starter.sql.');
  end if;
end;
/

create table s2_orders (
  order_id number(10) not null,
  status varchar2(10 char) not null,
  constraint s2_orders_pk primary key (order_id),
  constraint s2_orders_status_ck check (status in ('COMPLETE', 'CANCELLED'))
);
comment on table s2_orders is 'ACORDBANK_SESSION_2_V1';

create table s2_order_items (
  order_id number(10) not null,
  line_no number(5) not null,
  quantity number(12,3) not null,
  unit_price number(12,2) not null,
  constraint s2_order_items_pk primary key (order_id, line_no),
  constraint s2_items_order_fk foreign key (order_id) references s2_orders(order_id),
  constraint s2_items_quantity_ck check (quantity > 0),
  constraint s2_items_price_ck check (unit_price >= 0)
);
comment on table s2_order_items is 'ACORDBANK_SESSION_2_V1';

@@_seed.sql
@@settlement.pks.sql
@@settlement-starter.pkb.sql
@@_assert-compiled.sql
prompt INSTALL_OK: початкова версія встановлена; далі виконайте verify-baseline.sql.
exit success rollback
