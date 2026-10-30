"""Q2.4 实验原型：冻结入口验收期间只允许读取计划，计时实验另行受控运行。"""
from collections import defaultdict
import csv
from decimal import Decimal,ROUND_HALF_UP
import json
import re
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect
from scripts.verification_support import atomic_json,sha256

ORIGINAL="""SELECT c.customer_state, COUNT(DISTINCT o.order_id) AS orders,
SUM(oi.price) AS revenue, AVG(r.review_score) AS avg_score
FROM orders o
LEFT JOIN customers c ON o.customer_id=c.customer_id
LEFT JOIN order_items oi ON o.order_id=oi.order_id
LEFT JOIN order_reviews r ON o.order_id=r.order_id
WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= '2017-01-01'
AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state ORDER BY revenue DESC"""

CORRECTED="""WITH target_orders AS (
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
GROUP BY t.customer_state ORDER BY price_revenue DESC,t.customer_state"""


# 此版本只优化执行路径，故意保留原查询的重复计价与评价权重，用于等价性能对照。
EQUIVALENT="""SELECT NULLIF(c.customer_state,'') AS customer_state,
COUNT(DISTINCT o.order_id) AS orders,
SUM(CAST(NULLIF(oi.price,'') AS DECIMAL(20,3))) AS revenue,
AVG(CAST(NULLIF(r.review_score,'') AS SIGNED)) AS avg_score
FROM raw_orders o
JOIN raw_customers c ON o.customer_id=c.customer_id
LEFT JOIN raw_order_items oi ON o.order_id=oi.order_id
LEFT JOIN raw_order_reviews r ON o.order_id=r.order_id
WHERE o.order_status='delivered' AND o.order_purchase_timestamp >= '2017-01-01'
AND LOWER(c.customer_city) LIKE '%sao%'
GROUP BY c.customer_state ORDER BY revenue DESC"""


def reference():
    def rows(name):
        with (ROOT/'data/olist'/('olist_'+name+'_dataset.csv')).open(newline='',encoding='utf-8-sig') as stream:
            return list(csv.DictReader(stream))
    customers={r['customer_id']:r for r in rows('customers')}
    target={r['order_id']:customers[r['customer_id']]['customer_state'] for r in rows('orders')
        if r['order_status']=='delivered' and r['order_purchase_timestamp']>='2017-01-01'
        and 'sao' in customers[r['customer_id']]['customer_city'].lower()}
    items=defaultdict(list);reviews=defaultdict(list)
    for row in rows('order_items'):
        if row['order_id'] in target:items[row['order_id']].append(Decimal(row['price']))
    for line,row in enumerate(rows('order_reviews'),1):
        if row['order_id'] in target:
            reviews[row['order_id']].append((row['review_creation_date'],row['review_answer_timestamp'],row['review_id'],line,int(row['review_score'])))
    grouped=defaultdict(list)
    for oid,state in target.items():grouped[state].append(oid)
    corrected=[];original=[]
    def fixed(value,places):return str(value.quantize(Decimal(places),rounding=ROUND_HALF_UP))
    for state,orders in grouped.items():
        scores=[max(reviews[o])[-1] for o in orders if reviews[o]]
        price=sum((sum(items[o]) for o in orders),Decimal('0.000'))
        corrected.append({'customer_state':state,'orders':len(orders),'price_revenue':str(price),
            'avg_score':fixed(sum(map(Decimal,scores))/len(scores),'.000001') if scores else None,
            'reviewed_orders':len(scores),'missing_item_orders':sum(not items[o] for o in orders),'invalid_price_items':0})
        wrong_price=sum((sum(items[o])*max(1,len(reviews[o])) for o in orders),Decimal('0.000'))
        wrong_scores=[r[-1] for o in orders for r in reviews[o] for _ in range(max(1,len(items[o])))]
        original.append({'customer_state':state,'orders':len(orders),'revenue':str(wrong_price),
            'avg_score':fixed(sum(map(Decimal,wrong_scores))/len(wrong_scores),'.0001') if wrong_scores else None})
    return {'corrected':sorted(corrected,key=lambda r:(-Decimal(r['price_revenue']),r['customer_state'])),
            'original':sorted(original,key=lambda r:-Decimal(r['revenue'])),'target_orders':len(target)}


if __name__=='__main__':
    plans={}
    with connect() as c,c.cursor() as cur:
        for name,sql in [('original',ORIGINAL),('equivalent',EQUIVALENT),('corrected',CORRECTED)]:
            cur.execute('EXPLAIN FORMAT=JSON '+sql);plans[name]=json.loads(cur.fetchone()[0])
    atomic_json(ROOT/'reports/q2_4_plan_probe.json',{'experiment_sha256':sha256(Path(__file__)),
        'scope':'只读估计计划，不是实际计时或扫描行数；冻结原始 CSV 的显式键/金额转换假设', 'plans':plans})
    print('原始与修正查询估计计划已保存；尚未作性能结论')


def result_rows(connection,sql):
    with connection.cursor() as cur:
        cur.execute(sql);columns=[r[0] for r in cur.description]
        counts={'orders','reviewed_orders','missing_item_orders','invalid_price_items'}
        return [{k:int(v) if k in counts else str(v) if isinstance(v,Decimal) else v for k,v in zip(columns,row)} for row in cur.fetchall()]


def hand_probe():
    from scripts.verification_support import require
    with connect() as c,c.cursor() as cur:
        definitions={
            'orders':'order_id VARCHAR(32),customer_id VARCHAR(32),order_status VARCHAR(20),order_purchase_timestamp DATETIME',
            'customers':'customer_id VARCHAR(32),customer_state VARCHAR(2),customer_city VARCHAR(80)',
            'order_items':'order_id VARCHAR(32),price DECIMAL(20,3)',
            'order_reviews':'order_id VARCHAR(32),review_score INT,review_creation_date DATETIME,review_answer_timestamp DATETIME,review_id VARCHAR(32),_source_row BIGINT'}
        values={
            'orders':[('a','c1','delivered','2017-01-01'),('b','c2','delivered','2018-01-01'),('accent','c3','delivered','2017-01-01'),('old','c1','delivered','2016-12-31')],
            'customers':[('c1','SP','SAO PAULO'),('c2','SP','sao miguel'),('c3','SP','São Paulo')],
            'order_items':[('a',10),('a',20),('b',40),('accent',999),('old',999)],
            'order_reviews':[('a',1,'2017-01-02','2017-01-03','r1',1),('a',5,'2017-01-04','2017-01-05','r2',2),('b',4,'2018-01-02','2018-01-03','r3',3)]}
        for name,definition in definitions.items():
            for table in [name,'raw_'+name]:
                actual_definition=re.sub(r'DECIMAL\([^)]*\)|DATETIME|\bINT\b','VARCHAR(40)',definition) if table.startswith('raw_') else definition
                cur.execute(f'CREATE TEMPORARY TABLE {table} ({actual_definition}) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin')
                cur.executemany(f'INSERT INTO {table} VALUES ('+','.join(['%s']*len(values[name][0]))+')',values[name])
        # MySQL 不允许同一真实 TEMPORARY 表在该 CTE 展开中多次打开。
        # 以固定常量 CTE 承载原始层夹具，查询本体保持一致，不修改正式表。
        columns={'orders':['order_id','customer_id','order_status','order_purchase_timestamp'],
            'customers':['customer_id','customer_state','customer_city'],
            'order_items':['order_id','price'],
            'order_reviews':['order_id','review_score','review_creation_date','review_answer_timestamp','review_id','_source_row']}
        literals=[]
        for name,table_rows in values.items():
            selects=[]
            for index,row in enumerate(table_rows):
                cells=[]
                for column,value in zip(columns[name],row):
                    literal=c.escape(value if column=='_source_row' else str(value))
                    cells.append(literal+(' AS `'+column+'`' if index==0 else ''))
                selects.append('SELECT '+','.join(cells))
            literals.append('raw_'+name+' AS ('+' UNION ALL '.join(selects)+')')
        fixture_sql=CORRECTED.replace('WITH target_orders AS (','WITH '+', '.join(literals)+', target_orders AS (',1)
        original=result_rows(c,ORIGINAL);corrected=result_rows(c,fixture_sql)
        equivalent=result_rows(c,EQUIVALENT)
        require(equivalent==original,'等价提速版改变了原查询结果')
        require(original==[{'customer_state':'SP','orders':2,'revenue':'100.000','avg_score':'3.2000'}],f'原始错误未按手算出现：{original}')
        require(corrected==[{'customer_state':'SP','orders':2,'price_revenue':'70.000','avg_score':'4.500000','reviewed_orders':2,'missing_item_orders':0,'invalid_price_items':0}],f'修正不符手算：{corrected}')
        wrong=result_rows(c,fixture_sql.replace("LIKE '%sao%'","= 'sao paulo'"))
        require(wrong[0]['orders']!=2,'把子串条件改成精确城市未被识别')
        return {'original':original,'equivalent':equivalent,'corrected':corrected,'exact_city_mutant':wrong,
                'scope':'固定人工数据；包含大小写、重音、2016 排除与 2018 保留'}
