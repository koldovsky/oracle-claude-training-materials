declare
  l_mode varchar2(10) := :s2_verify_mode;
  l_checks pls_integer := 0;
  l_unexpected pls_integer := 0;
  l_known_failures pls_integer := 0;
  l_before varchar2(32767);
  l_after varchar2(32767);
  l_probe_count pls_integer;

  procedure record_check(p_label varchar2, p_ok boolean) is
  begin
    l_checks := l_checks + 1;
    if p_ok then
      dbms_output.put_line('[PASS] ' || p_label);
    else
      l_unexpected := l_unexpected + 1;
      dbms_output.put_line('[FAIL] ' || p_label);
    end if;
  end;

  function lab_snapshot return varchar2 is
    l_orders varchar2(16000);
    l_items varchar2(16000);
  begin
    select listagg(order_id || ':' || status, '|') within group (order by order_id)
      into l_orders from s2_orders;
    select listagg(order_id || ':' || line_no || ':' || quantity || ':' || unit_price, '|')
             within group (order by order_id, line_no)
      into l_items from s2_order_items;
    return l_orders || chr(10) || l_items;
  end;

  procedure run_case(
    p_label varchar2,
    p_api varchar2,
    p_id number,
    p_expected number default null,
    p_error pls_integer default 0,
    p_baseline_value number default null
  ) is
    l_actual number;
    l_code pls_integer := 0;
    l_expected number := p_expected;
    l_error pls_integer := p_error;
    l_known boolean := l_mode = 'BASELINE' and p_baseline_value is not null;
    l_ok boolean;
  begin
    if l_known then
      l_expected := p_baseline_value;
      l_error := 0;
    end if;

    begin
      if p_api = 'TOTAL' then
        l_actual := s2_settlement.order_total(p_id);
      elsif p_api = 'DUE' then
        l_actual := s2_settlement.merchant_due(p_id);
      else
        raise_application_error(-20995, 'Невідомий API у тесті.');
      end if;
    exception
      when others then
        l_code := sqlcode;
    end;

    l_ok := l_code = l_error;
    if l_error = 0 then
      l_ok := l_ok and l_actual is not null and l_actual = l_expected;
    end if;

    l_checks := l_checks + 1;
    if l_ok and l_known then
      l_known_failures := l_known_failures + 1;
      dbms_output.put_line('[KNOWN_FAIL] ' || p_label ||
        ' — відтворено дефект початкової версії.');
    elsif l_ok then
      dbms_output.put_line('[PASS] ' || p_label);
    else
      l_unexpected := l_unexpected + 1;
      dbms_output.put_line('[FAIL] ' || p_label ||
        '; отримано value=' || nvl(to_char(l_actual), 'NULL') ||
        ', SQLCODE=' || l_code ||
        '; очікується value=' || nvl(to_char(l_expected), 'NULL') ||
        ', SQLCODE=' || l_error);
    end if;
  end;
begin
  if l_mode not in ('BASELINE', 'FINAL') or l_mode is null then
    raise_application_error(-20995, 'Запускайте verify.sql або verify-baseline.sql.');
  end if;

  -- Незафіксовані рядки моделюють транзакцію виклику. Функції мають бачити її,
  -- зберегти рядки та SAVEPOINT і не виконувати власний COMMIT або ROLLBACK.
  select count(*) into l_probe_count from s2_orders where order_id = 1999;
  if l_probe_count <> 0 then
    raise_application_error(-20996,
      'Тестовий order_id=1999 уже зайнятий. Відновіть фікстури через reset-starter.sql.');
  end if;
  savepoint s2_verify_start;
  insert into s2_orders(order_id, status) values (1999, 'COMPLETE');
  insert into s2_order_items(order_id, line_no, quantity, unit_price)
    values (1999, 1, 1, 1.01);
  l_before := lab_snapshot;

  run_case('1001: сума кількох позицій 25.55', 'TOTAL', 1001, 25.55);
  run_case('1001: виплата після комісії 25.17', 'DUE', 1001, 25.17);
  run_case('1002: скасування не змінює суму позицій 99.99', 'TOTAL', 1002, 99.99);
  run_case('1002: виплата скасованого замовлення 0', 'DUE', 1002, 0,
           p_baseline_value => 98.49);
  run_case('1003: десяткова сума 0.30', 'TOTAL', 1003, 0.30);
  run_case('1003: округлення виплати до 0.30', 'DUE', 1003, 0.30);
  run_case('1004: порожнє замовлення має суму 0', 'TOTAL', 1004, 0);
  run_case('1004: порожнє замовлення має виплату 0', 'DUE', 1004, 0);
  run_case('1005: сума двох окремих позицій 0.68', 'TOTAL', 1005, 0.68);
  run_case('1005: округлення лише загальної виплати 0.67', 'DUE', 1005, 0.67);
  run_case('Невідомий ID: order_total повертає -20001', 'TOTAL', 999999,
           p_error => -20001, p_baseline_value => 0);
  run_case('Невідомий ID: merchant_due повертає -20001', 'DUE', 999999,
           p_error => -20001, p_baseline_value => 0);
  run_case('NULL: order_total повертає -20002', 'TOTAL', null,
           p_error => -20002, p_baseline_value => 0);
  run_case('NULL: merchant_due повертає -20002', 'DUE', null,
           p_error => -20002, p_baseline_value => 0);
  run_case('Власна транзакція: незбережена сума 1.01', 'TOTAL', 1999, 1.01);
  run_case('Власна транзакція: незбережена виплата 0.99', 'DUE', 1999, 0.99);

  l_after := lab_snapshot;
  record_check('Функції не змінили рядки лабораторії', l_before = l_after);
  begin
    rollback to s2_verify_start;
    select count(*) into l_probe_count from s2_orders where order_id = 1999;
    record_check('Транзакція виклику збережена; тестові рядки відкочено', l_probe_count = 0);
  exception
    when others then
      record_check('Транзакція виклику збережена; тестові рядки відкочено', false);
      dbms_output.put_line('Не вдалося повернутися до SAVEPOINT: ' || sqlerrm);
  end;

  if l_mode = 'BASELINE' and l_known_failures <> 5 then
    l_unexpected := l_unexpected + 1;
    dbms_output.put_line('[FAIL] Очікували рівно 5 відомих дефектів.');
  end if;

  if l_unexpected > 0 then
    raise_application_error(-20999,
      'VERIFY_FAIL: mode=' || l_mode || ', checks=' || l_checks ||
      ', unexpected=' || l_unexpected || ', known_failures=' || l_known_failures);
  end if;

  if l_mode = 'BASELINE' then
    dbms_output.put_line('BASELINE_CONFIRMED: checks=' || l_checks ||
      ', known_failures=5, unexpected=0');
  else
    dbms_output.put_line('ACCEPTANCE_PASS: checks=' || l_checks || ', unexpected=0');
  end if;
exception
  when others then
    -- При аварії прибираємо тільки зміни після тестового SAVEPOINT.
    begin
      rollback to s2_verify_start;
    exception
      when others then null;
    end;
    raise;
end;
/
