whenever sqlerror exit failure rollback
set serveroutput on
set define off

declare
  l_user varchar2(128) := sys_context('USERENV', 'SESSION_USER');
  l_schema varchar2(128) := sys_context('USERENV', 'CURRENT_SCHEMA');
begin
  if l_user not in ('TRAINER', 'TRAINEE1', 'TRAINEE2', 'TRAINEE3', 'TRAINEE4', 'TRAINEE5')
     or l_schema <> l_user then
    raise_application_error(-20990,
      'Лабораторію можна запускати лише у власній схемі TRAINER або TRAINEE1..5.');
  end if;
end;
/
