-- 卖家/订单先聚合，评价按确定性规则选一条；州内排名完成后再取平台 TOP20。
WITH seller_orders AS (
    SELECT order_id, seller_id, SUM(price + freight_value) AS amount,
           SUM(price IS NULL OR freight_value IS NULL) AS invalid_items
    FROM order_items GROUP BY order_id, seller_id
), review_choices AS (
    SELECT order_id, review_score,
           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY review_creation_date DESC,
               review_answer_timestamp DESC, review_id DESC, _source_row DESC) AS choice
    FROM order_reviews
), facts AS (
    SELECT i.*, o.order_status, c.customer_unique_id, c.customer_id, s.seller_state,
           o.order_delivered_customer_date AS actual_date, o.order_estimated_delivery_date AS estimated_date,
           r.review_score
    FROM seller_orders i
    STRAIGHT_JOIN orders o ON o.order_id=i.order_id
    STRAIGHT_JOIN sellers s ON s.seller_id=i.seller_id
    STRAIGHT_JOIN customers c ON c.customer_id=o.customer_id
    LEFT JOIN review_choices r ON r.order_id=o.order_id AND r.choice=1
    WHERE o.order_purchase_timestamp >= '2017-01-01' AND o.order_purchase_timestamp < '2018-01-01'
), aggregates AS (
    SELECT seller_id, seller_state,
           SUM(CASE WHEN order_status='delivered' THEN amount ELSE 0 END) AS gmv_2017,
           COUNT(*) AS order_count, COUNT(DISTINCT customer_unique_id) AS unique_customers,
           ROUND(AVG(CAST(review_score AS DECIMAL(20,10))),6) AS avg_review_score,
           ROUND(CAST(100 AS DECIMAL(30,12))*SUM(CASE WHEN order_status='delivered' AND actual_date>estimated_date THEN 1 ELSE 0 END)
               /NULLIF(SUM(order_status='delivered' AND actual_date IS NOT NULL AND estimated_date IS NOT NULL),0),6) AS late_delivery_rate,
           ROUND(CAST(100 AS DECIMAL(30,12))*SUM(order_status='canceled')/COUNT(*),6) AS cancel_rate,
           COUNT(review_score) AS reviewed_orders,
           SUM(order_status='delivered') AS delivered_orders,
           SUM(order_status='canceled') AS canceled_orders,
           SUM(order_status='delivered' AND actual_date IS NOT NULL AND estimated_date IS NOT NULL) AS valid_delivery_orders,
           SUM(order_status='delivered' AND (actual_date IS NULL OR estimated_date IS NULL)) AS missing_delivery_time_orders,
           SUM(CASE WHEN order_status='delivered' AND invalid_items>0 THEN 1 ELSE 0 END) AS invalid_amount_orders,
           SUM(customer_unique_id IS NULL OR seller_state IS NULL) AS missing_dimension_orders
    FROM facts GROUP BY seller_id,seller_state
), ranked AS (
    SELECT *, RANK() OVER (PARTITION BY seller_state ORDER BY gmv_2017 DESC) AS state_rank
    FROM aggregates
)
SELECT * FROM ranked ORDER BY gmv_2017 DESC, seller_id LIMIT 20;
