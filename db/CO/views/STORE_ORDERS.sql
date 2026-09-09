CREATE OR REPLACE FORCE EDITIONABLE VIEW "CO"."STORE_ORDERS" ("TOTAL", "STORE_NAME", "ADDRESS", "LATITUDE", "LONGITUDE", "ORDER_STATUS", "ORDER_COUNT", "TOTAL_SALES") DEFAULT COLLATION "USING_NLS_COMP"  AS 
  SELECT CASE
           grouping_id ( store_name, order_status )
           WHEN 1 THEN 'STORE TOTAL'
           WHEN 2 THEN 'STATUS TOTAL'
           WHEN 3 THEN 'GRAND TOTAL'
         END total,
         s.store_name,
         COALESCE ( s.web_address, s.physical_address ) address,
         s.latitude, s.longitude,
         o.order_status,
         COUNT ( DISTINCT o.order_id ) order_count,
         SUM ( oi.quantity * oi.unit_price ) total_sales
  FROM   stores s
  JOIN   orders o
  ON     s.store_id = o.store_id
  JOIN   order_items oi
  ON     o.order_id = oi.order_id
  GROUP  BY GROUPING SETS (
    ( s.store_name, COALESCE ( s.web_address, s.physical_address ), s.latitude, s.longitude ),
    ( s.store_name, COALESCE ( s.web_address, s.physical_address ), s.latitude, s.longitude, o.order_status ),
    o.order_status,
    ()
  );
