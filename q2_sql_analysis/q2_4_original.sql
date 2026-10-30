SELECT c.customer_state, COUNT(DISTINCT o.order_id) AS orders,
SUM(oi.price) AS revenue, AVG(r.review_score) AS avg_score
FROM orders o
LEFT JOIN customers c ON o.customer_id=c.customer_id
LEFT JOIN order_items oi ON o.order_id=oi.order_id
LEFT JOIN order_reviews r ON o.order_id=r.order_id
WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= '2017-01-01'
AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state ORDER BY revenue DESC;
