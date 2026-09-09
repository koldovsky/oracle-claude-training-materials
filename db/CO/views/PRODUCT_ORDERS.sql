CREATE OR REPLACE FORCE EDITIONABLE VIEW "CO"."PRODUCT_ORDERS" ("PRODUCT_NAME", "ORDER_STATUS", "TOTAL_SALES", "ORDER_COUNT") DEFAULT COLLATION "USING_NLS_COMP"  AS 
  SELECT p.product_name, o.order_status,
         SUM ( oi.quantity * oi.unit_price ) total_sales,
         COUNT (*) order_count
  FROM   orders o
  JOIN   order_items oi
  ON     o.order_id = oi.order_id
  JOIN   customers c
  ON     o.customer_id = c.customer_id
  JOIN   products p
  ON     oi.product_id = p.product_id
  GROUP  BY p.product_name, o.order_status;
