SELECT NULLIF(c.customer_state,'') AS customer_state,
COUNT(DISTINCT o.order_id) AS orders,
SUM(CAST(NULLIF(oi.price,'') AS DECIMAL(20,3))) AS revenue,
AVG(CAST(NULLIF(r.review_score,'') AS SIGNED)) AS avg_score
FROM raw_orders o
JOIN raw_customers c ON o.customer_id=c.customer_id
LEFT JOIN raw_order_items oi ON o.order_id=oi.order_id
LEFT JOIN raw_order_reviews r ON o.order_id=r.order_id
WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= '2017-01-01'
AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state ORDER BY revenue DESC;
