"""只读原始 CSV，提前核对 Q2.3 的关联与评价选择风险。"""
import csv
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'data/olist'
def rows(name):
    with (root/('olist_'+name+'_dataset.csv')).open(newline='',encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))
orders={r['order_id']:r for r in rows('orders') if '2017-01-01'<=r['order_purchase_timestamp']<'2018-01-01'}
items=rows('order_items');linked={r['order_id'] for r in items}
reviews=rows('order_reviews');c=Counter(r['order_id'] for r in reviews if r['order_id'] in orders)
print({'orders_2017':len(orders),'orders_without_items':sum(k not in linked for k in orders),'canceled_without_items':sum(k not in linked and v['order_status']=='canceled' for k,v in orders.items()),'orders_with_multiple_reviews':sum(n>1 for n in c.values())})
