"""九表来源及显式分析类型；原始暂存表保留所有字符串。"""

from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
NAMES=['customers','geolocation','order_items','order_payments','order_reviews','orders','products','sellers','product_category_name_translation']
INTEGER={'order_item_id','payment_sequential','payment_installments','review_score','product_name_lenght','product_description_lenght','product_photos_qty','product_weight_g','product_length_cm','product_height_cm','product_width_cm'}
MONEY={'price','freight_value','payment_value'}
GEO={'geolocation_lat','geolocation_lng'}
DATES={'shipping_limit_date','review_creation_date','review_answer_timestamp','order_purchase_timestamp','order_approved_at','order_delivered_carrier_date','order_delivered_customer_date','order_estimated_delivery_date'}
KEYS={'customers':['customer_id'],'geolocation':[],'order_items':['order_id','order_item_id'],
      'order_payments':['order_id','payment_sequential'],'order_reviews':[],'orders':['order_id'],'products':['product_id'],
      'sellers':['seller_id'],'product_category_name_translation':['product_category_name']}


def tables():
    files=json.loads((ROOT/'data_sources.json').read_text())['datasets']['olist']['files']
    by_filename={spec['source']:spec for spec in files}
    return {name:by_filename[name+'.csv' if name=='product_category_name_translation' else 'olist_'+name+'_dataset.csv'] for name in NAMES}


def expression(name):
    col=f'NULLIF(`{name}`,\'\')'
    if name in MONEY:
        return f'CAST({col} AS DECIMAL(20,3))'
    if name in GEO:
        return f'CAST({col} AS DECIMAL(30,20))'
    if name in INTEGER:
        return f'CAST(CAST({col} AS DECIMAL(20,3)) AS SIGNED)'
    if name in DATES:
        return f"STR_TO_DATE({col}, '%Y-%m-%d %H:%i:%s')"
    return col
