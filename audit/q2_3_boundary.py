"""补充独立边界实验：零成交、无评价、年界与评价排序完全同分。"""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verification_support import EvidenceRun,require,sha256
from q2_sql_analysis.mysql_runtime import connect
from q2_sql_analysis.q2_3 import execute,SQL


def probe():
    with connect() as c,c.cursor() as cur:
        for ddl in [
            'orders (order_id VARCHAR(32),order_status VARCHAR(20),customer_id VARCHAR(32),order_purchase_timestamp DATETIME,order_delivered_customer_date DATETIME,order_estimated_delivery_date DATETIME)',
            'order_items (order_id VARCHAR(32),seller_id VARCHAR(32),price DECIMAL(20,3),freight_value DECIMAL(20,3))',
            'sellers (seller_id VARCHAR(32),seller_state VARCHAR(2))',
            'customers (customer_id VARCHAR(32),customer_unique_id VARCHAR(32))',
            'order_reviews (order_id VARCHAR(32),review_score INT,review_creation_date DATETIME,review_answer_timestamp DATETIME,review_id VARCHAR(32),_source_row BIGINT)']:
            cur.execute('CREATE TEMPORARY TABLE '+ddl)
        cur.execute("INSERT INTO customers VALUES ('c','u')")
        cur.execute("INSERT INTO sellers VALUES ('zero','SP'),('valid','SP')")
        cur.execute("INSERT INTO orders VALUES ('canceled','canceled','c','2017-01-01',NULL,NULL),('good','delivered','c','2017-12-31 23:59:59','2018-01-03','2018-01-03'),('before','delivered','c','2016-12-31 23:59:59','2017-01-01','2017-01-01'),('after','delivered','c','2018-01-01','2018-01-02','2018-01-02')")
        cur.execute("INSERT INTO order_items VALUES ('canceled','zero',999,9),('good','valid',10,1),('before','valid',1000,100),('after','valid',1000,100)")
        cur.execute("INSERT INTO order_reviews VALUES ('good',1,'2018-01-04','2018-01-04','r',1),('good',5,'2018-01-04','2018-01-04','r',2)")
        rows=execute(c,SQL.read_text());by_id={r['seller_id']:r for r in rows}
        expected_zero={'gmv_2017':'0.000','order_count':1,'avg_review_score':None,'late_delivery_rate':None,'cancel_rate':'100.000000','reviewed_orders':0,'state_rank':2}
        expected_valid={'gmv_2017':'11.000','order_count':1,'avg_review_score':'5.000000','late_delivery_rate':'0.000000','cancel_rate':'0.000000','state_rank':1}
        for seller,expected in [('zero',expected_zero),('valid',expected_valid)]:
            require(all(by_id[seller][k]==v for k,v in expected.items()),f'{seller} 边界不符')
        return {'zero':expected_zero,'valid':expected_valid,'limit':'固定人工夹具；确定性同分选择不证明评价权威性'}


if __name__=='__main__':
    with EvidenceRun(ROOT/'reports/q2_3','boundary') as e:
        e.report['experiment_sha256']=sha256(Path(__file__))
        e.check('零成交、NULL、严格年界、相等不延迟、来源行同分',probe)
    raise SystemExit(0 if e.report['status']=='passed' else 1)
