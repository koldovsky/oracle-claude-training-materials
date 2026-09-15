declare
  l_count pls_integer;
begin
  for e in (
    select type, line, position, text
      from user_errors
     where name = 'S2_SETTLEMENT' and attribute = 'ERROR'
     order by type, sequence
  ) loop
    dbms_output.put_line(e.type || ' ' || e.line || ':' || e.position || ' ' || e.text);
  end loop;

  select count(*) into l_count
    from user_objects
   where object_name = 'S2_SETTLEMENT'
     and object_type in ('PACKAGE', 'PACKAGE BODY')
     and status = 'VALID';
  if l_count <> 2 then
    raise_application_error(-20993, 'Специфікація або тіло S2_SETTLEMENT не скомпільовані.');
  end if;

  select count(*) into l_count
    from user_errors
   where name = 'S2_SETTLEMENT' and attribute = 'ERROR';
  if l_count <> 0 then
    raise_application_error(-20993, 'У USER_ERRORS є помилки S2_SETTLEMENT.');
  end if;
end;
/
