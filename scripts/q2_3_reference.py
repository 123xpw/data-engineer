"""原始 CSV 字典独立复算，不调用 SQL 或生产聚合函数。"""
import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def read_reference():
    def read(name):
        with (ROOT/'data/olist'/('olist_'+name+'_dataset.csv')).open(encoding='utf-8-sig',newline='') as f:
            return list(csv.DictReader(f))
    orders={r['order_id']:r for r in read('orders') if '2017-01-01'<=r['order_purchase_timestamp']<'2018-01-01'}
    customers={r['customer_id']:r['customer_unique_id'] for r in read('customers')}
    states={r['seller_id']:r['seller_state'] for r in read('sellers')}
    reviews=defaultdict(list)
    for line,r in enumerate(read('order_reviews'),1):
        reviews[r['order_id']].append((r['review_creation_date'],r['review_answer_timestamp'],r['review_id'],line,int(r['review_score'])))
    pairs=defaultdict(lambda:Decimal(0));linked=set()
    for row in read('order_items'):
        oid=row['order_id']
        if oid in orders:
            linked.add(oid);pairs[(row['seller_id'],oid)]+=Decimal(row['price'])+Decimal(row['freight_value'])
    groups=defaultdict(list)
    for (seller,oid),amount in pairs.items():
        groups[seller].append((oid,amount))
    def rounded(value):
        return None if value is None else str(value.quantize(Decimal('.000001'),rounding=ROUND_HALF_UP))
    rows=[];sensitivity=[]
    for seller,items in groups.items():
        delivered=[oid for oid,_ in items if orders[oid]['order_status']=='delivered']
        valid=[oid for oid in delivered if orders[oid]['order_delivered_customer_date'] and orders[oid]['order_estimated_delivery_date']]
        late=sum(datetime.fromisoformat(orders[oid]['order_delivered_customer_date'])>datetime.fromisoformat(orders[oid]['order_estimated_delivery_date']) for oid in valid)
        canceled=sum(orders[oid]['order_status']=='canceled' for oid,_ in items)
        selected=[max(reviews[oid])[-1] for oid,_ in items if reviews[oid]]
        earliest=[min(reviews[oid])[-1] for oid,_ in items if reviews[oid]]
        means=[sum(Decimal(r[-1]) for r in reviews[oid])/len(reviews[oid]) for oid,_ in items if reviews[oid]]
        avg=lambda values:rounded(sum(map(Decimal,values))/len(values)) if values else None
        row={'seller_id':seller,'seller_state':states[seller],
             'gmv_2017':str(sum((amount for oid,amount in items if oid in delivered),Decimal('0.000'))),
             'order_count':len(items),'unique_customers':len({customers[orders[oid]['customer_id']] for oid,_ in items}),
             'avg_review_score':avg(selected),'late_delivery_rate':rounded(Decimal(late)*100/len(valid)) if valid else None,
             'cancel_rate':rounded(Decimal(canceled)*100/len(items)), 'reviewed_orders':len(selected),
             'delivered_orders':len(delivered),'canceled_orders':canceled,'valid_delivery_orders':len(valid),
             'missing_delivery_time_orders':len(delivered)-len(valid),'invalid_amount_orders':0,'missing_dimension_orders':0}
        rows.append(row)
        if avg(selected)!=avg(earliest) or avg(selected)!=avg(means):
            sensitivity.append({'seller_id':seller,'latest':avg(selected),'earliest':avg(earliest),'per_order_mean':avg(means)})
    for row in rows:
        row['state_rank']=1+sum(other['seller_state']==row['seller_state'] and Decimal(other['gmv_2017'])>Decimal(row['gmv_2017']) for other in rows)
    rows.sort(key=lambda r:(-Decimal(r['gmv_2017']),r['seller_id']))
    return {'top20':rows[:20],'all_sellers':rows,'orders_2017':len(orders),'attributed_orders':len(linked),
            'unattributed_orders':len(orders)-len(linked),
            'unattributed_canceled_orders':sum(r['order_status']=='canceled' for oid,r in orders.items() if oid not in linked),
            'delivered_gmv':str(sum(Decimal(r['gmv_2017']) for r in rows)),
            'review_sensitivity':sensitivity}
