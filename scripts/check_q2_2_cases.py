"""真实 MySQL 手算月度反例、变换与可运行错误注入；只使用临时表。"""

from decimal import Decimal as D
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect
from q2_sql_analysis.q2_2 import validate_months
from scripts.verification_support import EvidenceRun
from scripts.q2_2_reference import calculate

FIELDS=['month','total_orders','delivered_orders','canceled_orders','cancel_rate','delivered_gmv','avg_delivery_days',
        'valid_delivery_orders','missing_delivery_time_orders','delivered_missing_item_orders','delivered_invalid_amount_orders','negative_delivery_orders']
JAN=dict(zip(FIELDS,['2017-01',6,3,1,D('16.67'),D('54'),D('1.25'),2,1,0,0,0]))
FEB=dict(zip(FIELDS,['2017-02',1,0,1,D('100'),D('0'),None,0,0,0,0,0]))


def check_cases():
    sql=(ROOT/'q2_sql_analysis/q2_2_monthly_metrics.sql').read_text().replace('FROM order_items','FROM monthly_items').replace('FROM orders AS','FROM monthly_orders AS')
    with connect() as c,c.cursor() as cur:
        cur.execute('CREATE TEMPORARY TABLE monthly_orders (order_id VARCHAR(20) PRIMARY KEY, order_status VARCHAR(30), order_purchase_timestamp DATETIME, order_delivered_customer_date DATETIME)')
        cur.execute('CREATE TEMPORARY TABLE monthly_items (order_id VARCHAR(20), order_item_id INT, price DECIMAL(20,3), freight_value DECIMAL(20,3))')
        orders=[('A','delivered','2017-01-31 18:00:00','2017-02-01 06:00:00'),
                ('B','delivered','2017-01-10 00:00:00','2017-01-12 00:00:00'),
                ('C','delivered','2017-01-15 00:00:00',None),('D','canceled','2017-01-16 00:00:00',None),
                ('E','unavailable','2017-01-17 00:00:00',None),('F','shipped','2017-01-18 00:00:00',None),
                ('G','canceled','2017-02-01 00:00:00',None)]
        items=[('A',1,10,2),('A',2,10,2),('B',1,20,4),('C',1,5,1),('F',1,100,10)]
        reference,_=calculate(
            [dict(zip(['order_id','order_status','order_purchase_timestamp','order_delivered_customer_date'],[v or '' for v in row])) for row in orders],
            [dict(zip(['order_id','order_item_id','price','freight_value'],map(str,row))) for row in items])
        for observed,expected in zip(reference,[JAN,FEB]):
            assert {k:D(v) if k in ('cancel_rate','delivered_gmv','avg_delivery_days') and v is not None else v for k,v in observed.items()}==expected,'独立参考未通过手算校准'
        assert len(reference)==2
        def reset():
            cur.execute('DELETE FROM monthly_items');cur.execute('DELETE FROM monthly_orders')
            cur.executemany('INSERT INTO monthly_orders VALUES (%s,%s,%s,%s)',orders)
            cur.executemany('INSERT INTO monthly_items VALUES (%s,%s,%s,%s)',items)
        def execute(text=sql):
            cur.execute(text);columns=[col[0] for col in cur.description]
            rows=[dict(zip(columns,row)) for row in cur.fetchall()]
            cur.execute('SHOW COUNT(*) WARNINGS');assert cur.fetchone()[0]==0,'实验 SQL 产生警告'
            return rows
        reset();assert execute()==[JAN,FEB],'基础手算结果不同'
        mutations={
            'inner_join':('LEFT JOIN item_totals','INNER JOIN item_totals'),
            'item_weighting':('GROUP BY order_id','GROUP BY order_id, order_item_id'),
            'omit_freight':('SUM(price + freight_value)','SUM(price)'),
            'sum_distinct':('SUM(price + freight_value)','SUM(DISTINCT price + freight_value)'),
            'all_status_gmv':("THEN amount ELSE 0 END","THEN amount ELSE amount END"),
            'partial_cancel_denominator':("/ COUNT(*), 2)","/ SUM(order_status IN ('delivered','canceled')), 2)"),
            'unavailable_is_canceled':("order_status = 'canceled'","order_status IN ('canceled','unavailable')"),
            'delivery_month':("DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')","DATE_FORMAT(o.order_delivered_customer_date, '%Y-%m')"),
            'missing_time_zero':("SUM(order_status = 'delivered' AND delivery_seconds IS NOT NULL)","SUM(order_status = 'delivered')"),
            'whole_days':('THEN delivery_seconds END','THEN FLOOR(delivery_seconds / 86400) * 86400 END'),
        }
        captured={}
        for name,(old,new) in mutations.items():
            assert old in sql,f'变体 {name} 定位失败'
            actual=execute(sql.replace(old,new))
            # SQL 错误在 execute 中直接失败，不算成功捕获。
            rejected=False
            try:
                assert actual==[JAN,FEB]
            except AssertionError:
                rejected=True
            assert rejected,f'可运行错误 {name} 逃过手算断言'
            captured[name]={'executed':True,'numeric_assertion_rejected':True}
        cur.execute("DELETE FROM monthly_items WHERE order_id='B'")
        cur.executemany('INSERT INTO monthly_items VALUES (%s,%s,%s,%s)',[('B',1,10,2),('B',2,10,2)])
        assert execute()==[JAN,FEB],'等额拆分明细改变订单指标'
        reset()
        cur.execute("INSERT INTO monthly_orders VALUES ('H','delivered','2017-01-10','2017-01-12')")
        cur.execute("INSERT INTO monthly_items VALUES ('H',1,20,4)")
        extra=execute()[0]
        assert extra['delivered_gmv']==D('78') and extra['total_orders']==7,'新同额订单被误去重'
        # 独立的极端组：整个月只有缺送达时间的 delivered 订单。
        reset();cur.execute('DELETE FROM monthly_orders');cur.execute('DELETE FROM monthly_items')
        cur.execute("INSERT INTO monthly_orders VALUES ('Z','delivered','2017-03-01',NULL)")
        cur.execute("INSERT INTO monthly_items VALUES ('Z',1,5,1)")
        expected=dict(zip(FIELDS,['2017-03',1,1,0,D('0'),D('6'),None,0,1,0,0,0]))
        assert execute()==[expected],'全组缺时长时诊断或平均值错误'
        validate_months([expected])
        cur.execute('SAVEPOINT fractional_second')
        cur.execute("UPDATE monthly_orders SET order_delivered_customer_date='2017-03-01 00:00:01'")
        precise=execute()[0]
        assert precise['avg_delivery_days']==D('0.000012'),f"一秒时长过早舍入：{precise['avg_delivery_days']}"
        cur.execute('ROLLBACK TO SAVEPOINT fractional_second')
        cur.execute('SAVEPOINT rounding_tie')
        cur.execute("UPDATE monthly_orders SET order_delivered_customer_date='2017-03-01 00:00:02'")
        cur.executemany('INSERT INTO monthly_orders VALUES (%s,%s,%s,%s)',[
            ('Z2','delivered','2017-03-01 00:00:00','2017-03-01 00:00:02'),
            ('Z3','delivered','2017-03-01 00:00:00','2017-03-01 00:01:17')])
        cur.executemany('INSERT INTO monthly_items VALUES (%s,%s,%s,%s)',[('Z2',1,5,1),('Z3',1,5,1)])
        tied=execute()[0]
        assert tied['avg_delivery_days']==D('0.000313'),f"恰好半单位的平均值舍入错误：{tied['avg_delivery_days']}"
        cur.execute('ROLLBACK TO SAVEPOINT rounding_tie')
        edge_results={}
        for name,statement in [
            ('missing_items','DELETE FROM monthly_items'),
            ('missing_amount','UPDATE monthly_items SET price=NULL'),
            ('negative_duration',"UPDATE monthly_orders SET order_delivered_customer_date='2017-02-28'"),
            ('missing_purchase','UPDATE monthly_orders SET order_purchase_timestamp=NULL')]:
            cur.execute('SAVEPOINT edge_case');cur.execute(statement)
            actual=execute()
            rejected=False
            try:
                validate_months(actual)
            except ValueError:
                rejected=True
            assert rejected,f'{name} 未阻止正式发布'
            if name in ('missing_items','missing_amount'):
                assert actual[0]['delivered_gmv'] is None,'未知金额被补零'
            edge_results[name]=True
            cur.execute('ROLLBACK TO SAVEPOINT edge_case')
        cur.execute('DELETE FROM monthly_orders');cur.execute('DELETE FROM monthly_items')
        assert execute()==[]
        try:
            validate_months([])
        except ValueError:
            pass
        else:
            raise AssertionError('空正式输入当成功')
        return {'synthetic':True,'handcalculated_january':{k:str(v) if isinstance(v,D) else v for k,v in JAN.items()},
                'mutations':captured,'split_items_invariant':True,'same_amount_new_order_additive':True,
                'all_delivery_times_missing':True,'one_second_precision':True,'exact_rounding_tie':True,'critical_diagnostics_block_publish':edge_results,'empty_query_rows':0,
                'limitation':'定向变体有限，不能把捕获比例当业务准确率'}


if __name__=='__main__':
    with EvidenceRun(ROOT/'reports/q2_2','sql_cases') as e:
        e.check('MySQL 手算、可运行错误、变换与异常组',check_cases)
    print(e.path)
    raise SystemExit(0 if e.report['status']=='passed' else 1)
