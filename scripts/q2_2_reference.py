"""直接从原始 CSV 以订单字典复算月指标；不导入生产 SQL 或聚合函数。"""

from collections import Counter,defaultdict
import csv
from datetime import datetime
from decimal import Decimal as D,ROUND_HALF_UP
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def rounded(value,places):
    return str(value.quantize(D(places),rounding=ROUND_HALF_UP))


def calculate(orders,items):
    assert len({o['order_id'] for o in orders})==len(orders),'参考数据订单键重复'
    by_order=defaultdict(list)
    for item in items:
        by_order[item['order_id']].append(item)
    months=defaultdict(list)
    for order in orders:
        months[order['order_purchase_timestamp'][:7] or None].append(order)
    result=[]
    totals={'order_status':dict(Counter(o['order_status'] for o in orders)),
            'no_items_by_status':dict(Counter(o['order_status'] for o in orders if not by_order[o['order_id']]))}
    naive_count=naive_cancel=inner_count=inner_cancel=0
    exact_seconds=weighted_seconds=valid=weighted_valid=delivered=0
    for month,group in sorted(months.items(),key=lambda pair:pair[0] or ''):
        n=len(group);ds=[o for o in group if o['order_status']=='delivered'];cs=sum(o['order_status']=='canceled' for o in group)
        amount=D(0);unknown_amount=False;seconds=[];missing_items=invalid_amount=negative=0
        for order in group:
            detail=by_order[order['order_id']];weight=max(1,len(detail))
            naive_count+=weight;inner_count+=len(detail)
            if order['order_status']=='canceled':
                naive_cancel+=weight;inner_cancel+=len(detail)
            if order['order_status']!='delivered':
                continue
            delivered+=1
            if not detail:
                missing_items+=1;unknown_amount=True
            if any(not item['price'] or not item['freight_value'] for item in detail):
                invalid_amount+=1;unknown_amount=True
            else:
                amount+=sum((D(item['price'])+D(item['freight_value']) for item in detail),D(0))
            if order['order_purchase_timestamp'] and order['order_delivered_customer_date']:
                duration=datetime.fromisoformat(order['order_delivered_customer_date'])-datetime.fromisoformat(order['order_purchase_timestamp'])
                sec=duration.days*86400+duration.seconds
                seconds.append(sec);negative+=sec<0
                exact_seconds+=sec;valid+=1;weighted_seconds+=sec*weight;weighted_valid+=weight
        result.append({'month':month,'total_orders':n,'delivered_orders':len(ds),'canceled_orders':cs,
            'cancel_rate':rounded(D(cs)*100/n,'.01'),'delivered_gmv':None if unknown_amount else rounded(amount,'.001'),
            'avg_delivery_days':rounded(D(sum(seconds))/len(seconds)/86400,'.000001') if seconds else None,
            'valid_delivery_orders':len(seconds),'missing_delivery_time_orders':len(ds)-len(seconds),
            'delivered_missing_item_orders':missing_items,'delivered_invalid_amount_orders':invalid_amount,'negative_delivery_orders':negative})
    totals['wrong_join_experiment']={'correct_orders':len(orders),'left_detail_rows':naive_count,'inner_detail_rows':inner_count,
        'correct_canceled':sum(o['order_status']=='canceled' for o in orders),'left_join_canceled_rows':naive_cancel,'inner_join_canceled_rows':inner_cancel,
        'correct_avg_days':rounded(D(exact_seconds)/valid/86400,'.000001') if valid else None,
        'detail_weighted_avg_days':rounded(D(weighted_seconds)/weighted_valid/86400,'.000001') if weighted_valid else None,
        'missing_time_zero_avg_days':rounded(D(exact_seconds)/delivered/86400,'.000001') if delivered else None,
        'valid_delivery_orders':valid,'delivered_orders':delivered}
    return result,totals


def read_reference():
    from scripts.verification_support import sha256
    specs=json.loads((ROOT/'data_sources.json').read_text())['datasets']['olist']['files']
    records=[];hashes={}
    for name in ('olist_orders_dataset.csv','olist_order_items_dataset.csv'):
        spec=next(s for s in specs if s['source']==name)
        path=ROOT/'data'/spec['target'];actual=sha256(path);assert actual==spec['sha256']
        hashes[spec['target']]=actual
        with path.open(encoding='utf-8-sig',newline='') as stream:
            records.append(list(csv.DictReader(stream)))
    rows,diagnostics=calculate(*records)
    return {'months':rows,'diagnostics':diagnostics,'source_sha256':hashes,
            'scope':'独立原始 CSV 复算与错误口径敏感性；错误口径不是正式结果'}
