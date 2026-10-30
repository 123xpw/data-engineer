WITH target_orders AS (
    SELECT DISTINCT o.order_id, NULLIF(c.customer_state,'') AS customer_state
    FROM raw_orders o JOIN raw_customers c ON o.customer_id=c.customer_id
    WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= '2017-01-01'
      AND LOWER(c.customer_city) LIKE '%sao%'
), item_totals AS (
    SELECT i.order_id, SUM(CAST(NULLIF(i.price,'') AS DECIMAL(20,3))) AS price_revenue,
           SUM(i.price='') AS invalid_price_items
    FROM raw_order_items i JOIN target_orders t ON t.order_id=i.order_id
    GROUP BY i.order_id
), review_candidates AS (
    SELECT r.order_id, CAST(NULLIF(r.review_score,'') AS SIGNED) AS review_score,
           ROW_NUMBER() OVER (PARTITION BY r.order_id ORDER BY r.review_creation_date DESC,
               r.review_answer_timestamp DESC,r.review_id DESC,r._source_row DESC) AS choice
    FROM raw_order_reviews r JOIN target_orders t ON t.order_id=r.order_id
)
SELECT t.customer_state, COUNT(*) AS orders, SUM(i.price_revenue) AS price_revenue,
       ROUND(AVG(CAST(r.review_score AS DECIMAL(20,10))),6) AS avg_score,
       COUNT(r.review_score) AS reviewed_orders,
       SUM(i.order_id IS NULL) AS missing_item_orders,
       SUM(COALESCE(i.invalid_price_items,0)) AS invalid_price_items
FROM target_orders t LEFT JOIN item_totals i ON i.order_id=t.order_id
LEFT JOIN review_candidates r ON r.order_id=t.order_id AND r.choice=1
GROUP BY t.customer_state ORDER BY price_revenue DESC,t.customer_state;
