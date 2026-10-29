-- Q2.1：有名类别没有有效英文对照；未知类别单独报告，不能算作类别名称。
-- NOT EXISTS 避免翻译表重复行放大商品数。比较遵循表的 utf8mb4_0900_bin。
SELECT p.product_category_name, COUNT(*) AS product_count
FROM products AS p
WHERE p.product_category_name IS NOT NULL
  AND p.product_category_name <> ''
  AND NOT EXISTS (
      SELECT 1
      FROM product_category_name_translation AS t
      WHERE t.product_category_name = p.product_category_name
        AND t.product_category_name_english IS NOT NULL
        AND TRIM(t.product_category_name_english) <> ''
  )
GROUP BY p.product_category_name
ORDER BY p.product_category_name;
