create or replace package s2_settlement authid definer as
  -- ACORDBANK_SESSION_2_V1
  function order_total(p_order_id number) return number;
  function merchant_due(p_order_id number) return number;
end s2_settlement;
/
