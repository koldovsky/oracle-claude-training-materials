create or replace package body s2_settlement as
  function order_total(p_order_id number) return number is
    l_status s2_orders.status%type;
    l_total number := 0;
  begin
    select status into l_status
      from s2_orders
     where order_id = p_order_id;

    for r in (
      select quantity, unit_price
        from s2_order_items
       where order_id = p_order_id
       order by line_no
    ) loop
      l_total := l_total + r.quantity * r.unit_price;
    end loop;
    return l_total;
  exception
    when others then
      return 0;
  end order_total;

  function merchant_due(p_order_id number) return number is
    l_status s2_orders.status%type;
    l_total number := 0;
  begin
    select status into l_status
      from s2_orders
     where order_id = p_order_id;

    for r in (
      select quantity, unit_price
        from s2_order_items
       where order_id = p_order_id
       order by line_no
    ) loop
      l_total := l_total + r.quantity * r.unit_price;
    end loop;
    return round(l_total * 0.985, 2);
  exception
    when others then
      return 0;
  end merchant_due;
end s2_settlement;
/
