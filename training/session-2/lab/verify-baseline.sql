-- Успіх означає саме п'ять відомих дефектів початкової версії, а не готове рішення.
whenever oserror exit failure rollback
whenever sqlerror exit failure rollback
set serveroutput on
set define off
@@_assert-lab.sql
@@_assert-compiled.sql
variable s2_verify_mode varchar2(10)
begin
  :s2_verify_mode := 'BASELINE';
end;
/
@@_acceptance-checks.sql
exit success rollback
