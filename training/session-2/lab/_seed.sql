insert into s2_orders(order_id, status) values (1001, 'COMPLETE');
insert into s2_orders(order_id, status) values (1002, 'CANCELLED');
insert into s2_orders(order_id, status) values (1003, 'COMPLETE');
insert into s2_orders(order_id, status) values (1004, 'COMPLETE');
insert into s2_orders(order_id, status) values (1005, 'COMPLETE');

insert into s2_order_items(order_id, line_no, quantity, unit_price) values (1001, 1, 2, 10.00);
insert into s2_order_items(order_id, line_no, quantity, unit_price) values (1001, 2, 1, 5.55);
insert into s2_order_items(order_id, line_no, quantity, unit_price) values (1002, 1, 1, 99.99);
insert into s2_order_items(order_id, line_no, quantity, unit_price) values (1003, 1, 3, 0.10);
insert into s2_order_items(order_id, line_no, quantity, unit_price) values (1005, 1, 1, 0.34);
insert into s2_order_items(order_id, line_no, quantity, unit_price) values (1005, 2, 1, 0.34);
commit;
