"""固定手算数据在临时表执行；表只在本连接可见，不修改项目原表。"""
from q2_sql_analysis.mysql_runtime import connect
from q2_sql_analysis.q2_3 import SQL,execute
from scripts.verification_support import require


def check_cases():
    with connect() as c,c.cursor() as cur:
        definitions={
            'orders':'order_id VARCHAR(32),order_status VARCHAR(20),customer_id VARCHAR(32),order_purchase_timestamp DATETIME,order_delivered_customer_date DATETIME,order_estimated_delivery_date DATETIME',
            'order_items':'order_id VARCHAR(32),seller_id VARCHAR(32),price DECIMAL(20,3),freight_value DECIMAL(20,3)',
            'sellers':'seller_id VARCHAR(32),seller_state VARCHAR(2)',
            'customers':'customer_id VARCHAR(32),customer_unique_id VARCHAR(32)',
            'order_reviews':'order_id VARCHAR(32),review_score INT,review_creation_date DATETIME,review_answer_timestamp DATETIME,review_id VARCHAR(32),_source_row BIGINT'}
        for name,definition in definitions.items():
            cur.execute(f'CREATE TEMPORARY TABLE {name} ({definition})')
        def insert(table,values):
            cur.executemany(f'INSERT INTO {table} VALUES ('+','.join(['%s']*len(values[0]))+')',values)
        insert('customers',[('c1','u1'),('c2','u1')])
        insert('orders',[(oid,status,customer,'2017-01-01 00:00:00',actual,'2017-01-02 00:00:00') for oid,status,customer,actual in [
            ('o1','delivered','c1','2017-01-03 00:00:00'),('o2','delivered','c2',None),('o3','canceled','c1',None),
            ('o4','delivered','c1','2017-01-02 00:00:00'),('o5','delivered','c1','2017-01-02 00:00:00')]])
        insert('sellers',[('A','SP'),('B','RJ'),('C','SP'),('D','SP')]+[(f'x{i:02}','ZZ') for i in range(21)])
        insert('order_items',[('o1','A',60,6),('o1','A',40,4),('o2','A',30,3),('o3','A',9,1),('o1','B',45,5),('o4','C',130,13),('o5','D',18,2)]+[('o4',f'x{i:02}',1,0) for i in range(21)])
        insert('order_reviews',[('o1',1,'2017-01-03','2017-01-04','r1',1),('o1',5,'2017-01-05','2017-01-06','r2',2),('o2',3,'2017-01-05','2017-01-06','r3',3),('o3',1,'2017-01-05','2017-01-06','r4',4)])
        sql=SQL.read_text();actual=execute(c,sql)
        require([r['seller_id'] for r in actual]==['A','C','B','D']+[f'x{i:02}' for i in range(16)],'TOP20、并列或稳定排序错误')
        a=actual[0]
        expected={'gmv_2017':'143.000','order_count':3,'unique_customers':1,'avg_review_score':'3.000000','late_delivery_rate':'100.000000','cancel_rate':'33.333333','state_rank':1,'reviewed_orders':3,'valid_delivery_orders':1,'missing_delivery_time_orders':1}
        require(all(a[k]==v for k,v in expected.items()),f'固定手算不符：{a}')
        require(actual[3]['state_rank']==3,'州内并列后排名跳号错误')
        variants={
            '省略运费':sql.replace('SUM(price + freight_value)','SUM(price)'),
            '评价未去重':sql.replace('r.choice=1','r.choice>=1'),
            '以客户订单标识冒充自然客户':sql.replace('COUNT(DISTINCT customer_unique_id)','COUNT(DISTINCT customer_id)'),
            '全平台排名冒充州内排名':sql.replace('PARTITION BY seller_state ORDER BY gmv_2017 DESC','ORDER BY gmv_2017 DESC')}
        changes={}
        for name,variant in variants.items():
            wrong=execute(c,variant)
            differences=[{'seller_id':r['seller_id'],'fields':[k for k in r if r[k]!=next(x for x in actual if x['seller_id']==r['seller_id'])[k]]} for r in wrong if r['seller_id'] in {x['seller_id'] for x in actual}]
            differences=[d for d in differences if d['fields']]
            require(bool(differences),f'错误 SQL 未产生预期数值差异：{name}')
            changes[name]=differences[:3]
        return {'fixed_expected_A':expected,'actual_A':a,'top20_stable':True,'mutations':changes,'scope':'人工样例；真实数据另行独立复算'}
