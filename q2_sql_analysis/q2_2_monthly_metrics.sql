-- 先将金额聚合到订单，避免商品数量改变订单数和平均送达时长。
WITH item_totals AS (
    SELECT order_id, SUM(price + freight_value) AS amount,
           SUM(price IS NULL OR freight_value IS NULL) AS invalid_amount_items
    FROM order_items
    GROUP BY order_id
), order_facts AS (
    SELECT o.order_id, o.order_status,
           DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS month,
           i.amount, i.order_id IS NULL AS missing_items,
           COALESCE(i.invalid_amount_items, 0) AS invalid_amount_items,
           TIMESTAMPDIFF(SECOND, o.order_purchase_timestamp, o.order_delivered_customer_date) AS delivery_seconds
    FROM orders AS o
    LEFT JOIN item_totals AS i ON i.order_id = o.order_id
)
SELECT month,
       COUNT(*) AS total_orders,
       SUM(order_status = 'delivered') AS delivered_orders,
       SUM(order_status = 'canceled') AS canceled_orders,
       ROUND(100.0 * SUM(order_status = 'canceled') / COUNT(*), 2) AS cancel_rate,
       CASE WHEN SUM(order_status = 'delivered' AND (missing_items OR invalid_amount_items > 0)) > 0
            THEN NULL
            ELSE SUM(CASE WHEN order_status = 'delivered' THEN amount ELSE 0 END)
       END AS delivered_gmv,
       -- 先精确累计整数秒，再一次除以有效订单数与每天秒数；避免逐单换算的累计舍入。
       ROUND(CAST(SUM(CASE WHEN order_status = 'delivered' THEN delivery_seconds END) AS DECIMAL(30,12))
             / NULLIF(SUM(order_status = 'delivered' AND delivery_seconds IS NOT NULL) * 86400, 0), 6) AS avg_delivery_days,
       -- 以下诊断列用于公开分母及异常，不改变题目要求的七个指标。
       SUM(order_status = 'delivered' AND delivery_seconds IS NOT NULL) AS valid_delivery_orders,
       SUM(order_status = 'delivered' AND delivery_seconds IS NULL) AS missing_delivery_time_orders,
       SUM(order_status = 'delivered' AND missing_items) AS delivered_missing_item_orders,
       SUM(order_status = 'delivered' AND invalid_amount_items > 0) AS delivered_invalid_amount_orders,
       SUM(CASE WHEN order_status = 'delivered' AND delivery_seconds < 0 THEN 1 ELSE 0 END) AS negative_delivery_orders
FROM order_facts
GROUP BY month
ORDER BY month;
