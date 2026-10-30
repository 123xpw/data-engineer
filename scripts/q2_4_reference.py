"""原始 CSV 独立复算原查询与业务修正版，不调用生产 SQL。"""
from collections import defaultdict
import csv
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def read_reference():
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

