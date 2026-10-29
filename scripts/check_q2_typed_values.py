"""独立核对分析值归属，并用保留汇总数的错误实验检查验证盲区。"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import connect
from scripts.verification_support import EvidenceRun

# 依据字段含义独立列出，不导入生产 catalog 的类型集合或 SQL 表达式。
DECIMALS={'order_items':{'price','freight_value'},'order_payments':{'payment_value'},
          'geolocation':{'geolocation_lat','geolocation_lng'}}
INTEGERS={'order_items':{'order_item_id'},'order_payments':{'payment_sequential','payment_installments'},
          'order_reviews':{'review_score'},'products':{'product_name_lenght','product_description_lenght',
          'product_photos_qty','product_weight_g','product_length_cm','product_height_cm','product_width_cm'}}
TIMES={'order_items':{'shipping_limit_date'},'order_reviews':{'review_creation_date','review_answer_timestamp'},
       'orders':{'order_purchase_timestamp','order_approved_at','order_delivered_carrier_date',
                 'order_delivered_customer_date','order_estimated_delivery_date'}}


def expected_values(table,columns,values):
    result=[]
    for column,value in zip(columns,values):
        if value=='':
            converted=None
        elif column in DECIMALS.get(table,set()):
            converted=Decimal(value)
        elif column in INTEGERS.get(table,set()):
            exact=Decimal(value)
            converted=int(exact)
            assert Decimal(converted)==exact,'参考整数转换有损'
        elif column in TIMES.get(table,set()):
            converted=datetime.fromisoformat(value)
        else:
            converted=value
        result.append(converted)
    return tuple(result)


def assert_record(actual,expected,context):
    assert actual is not None and len(actual)==len(expected),f'{context} 缺记录或列数变化'
    for position,(found,wanted) in enumerate(zip(actual,expected)):
        assert type(found) is type(wanted) and found==wanted,f'{context} 第 {position} 列的类型或归属值不符'


def check_blindspot():
    """合成小表，正式表不变；仅明确断言失败才算抓住可运行错误。"""
    with connect() as c,c.cursor() as cur:
        cur.execute('CREATE TEMPORARY TABLE type_probe (source_row INT PRIMARY KEY, amount DECIMAL(20,3), happened DATETIME)')
        cur.executemany('INSERT INTO type_probe VALUES (%s,%s,%s)',[
            (1,Decimal('10'),'2017-01-31 12:00:00'),(2,Decimal('20'),'2017-02-02 06:00:00'),(3,None,None)])
        expected=[(1,Decimal('10'),datetime(2017,1,31,12)),(2,Decimal('20'),datetime(2017,2,2,6)),(3,None,None)]
        variants={
            'correct':'SELECT source_row,amount,happened FROM type_probe',
            'date_shift':'SELECT source_row,amount,DATE_ADD(happened, INTERVAL 1 DAY) happened FROM type_probe',
            'amount_reassigned':'SELECT source_row,CASE source_row WHEN 1 THEN CAST(20 AS DECIMAL(20,3)) WHEN 2 THEN CAST(10 AS DECIMAL(20,3)) ELSE amount END amount,happened FROM type_probe',
        }
        baseline_summary=None;result={}
        for name,sql in variants.items():
            cur.execute('SELECT COUNT(*),SUM(amount IS NULL),SUM(happened IS NULL),SUM(amount) FROM ('+sql+') x')
            summary=cur.fetchone()
            if name=='correct':
                baseline_summary=summary
            assert summary==baseline_summary,'实验没有保持原检查的汇总条件'
            cur.execute(sql+' ORDER BY source_row');rows=cur.fetchall()
            rejected=False
            try:
                assert len(rows)==len(expected)
                for actual,wanted in zip(rows,expected):
                    assert_record(actual,wanted,name)
            except AssertionError:
                rejected=True
            assert rejected==(name!='correct'),'逐记录检查未区分正确与错误输出'
            result[name]={'old_summary_checks_pass':True,'row_value_check_rejects':rejected,
                          'rows':len(rows),'sum_amount':str(summary[-1])}
        return {'synthetic':True,'real_mysql':True,'temporary_table_only':True,'variants':result,
                'limitation':'只证明这两类值归属错误可绕过旧汇总检查，不代表生产视图曾出现该错误或已覆盖所有错误'}


if __name__=='__main__':
    with EvidenceRun(ROOT/'reports/q2_1','typed_blindspot') as e:
        e.check('保持汇总数的错误输出与逐记录判别',check_blindspot)
    print(e.path)
    raise SystemExit(0 if e.report['status']=='passed' else 1)
