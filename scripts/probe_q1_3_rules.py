"""审查已有候选视图的用途风险；不实现退货匹配或自动清洗。"""

import csv
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from download_data import load_sources,verify_file


def probe(path):
    # 已知极值所在客户是调查对象，不用此单个客户代表全体客户。
    records=[]
    with Path(path).open(newline='',encoding='utf-8-sig') as stream:
        for number,row in enumerate(csv.DictReader(stream),1):
            if row['Customer ID']=='16446.0':
                records.append({'record':number,**row})
    amount=lambda row:Decimal(row['Quantity'])*Decimal(row['Price'])
    candidate=[r for r in records if re.fullmatch('[0-9]+',r['Invoice']) and re.fullmatch('[0-9]+[A-Za-z]*',r['StockCode']) and Decimal(r['Quantity'])>0 and Decimal(r['Price'])>0]
    pair=[r for r in records if abs(Decimal(r['Quantity']))==80995]
    assert len(pair)==2 and sum(map(amount,pair))==0
    pair=sorted(pair,key=lambda r:r['InvoiceDate'])
    assert [Decimal(r['Quantity']) for r in pair]==[Decimal(80995),Decimal(-80995)]
    assert pair[0]['StockCode']==pair[1]['StockCode'] and pair[0]['Price']==pair[1]['Price']
    assert pair[1]['Invoice'].startswith('C')
    rest=[r for r in candidate if r not in pair]
    view=lambda rows:{'rows':len(rows),'gross':str(sum(map(amount,rows),Decimal(0))),
                       'invoices':len({r['Invoice'] for r in rows}),'latest_purchase':max((r['InvoiceDate'] for r in rows),default=None)}
    return {'scope':'已知极值客户的个案反例，不代表总体，也未确认真实匹配', 'customer':'16446.0',
            'records':records,'candidate':view(candidate),'if_extreme_purchase_is_confirmed_cancelled':view(rest),
            'pair_net':str(sum(map(amount,pair))),'pair_positive_amount':str(amount(pair[0])),
            'pair_time_seconds':(datetime.fromisoformat(pair[1]['InvoiceDate'])-datetime.fromisoformat(pair[0]['InvoiceDate'])).total_seconds(),
            'pair_candidate_rows':len([r for r in candidate if r in pair]),
            'raw_customer_net':str(sum(map(amount,records))),
            'raw_net_warning':'原始客户净额另含 TEST001 的 -9.00，不等于认证商品净额；不能用个案条件情景直接替换生产结果',
            'synthetic_cases':{
                'partial_return':{'scope':'手算合成；假定唯一关联已确认','purchased':3,'returned':1,'unit_price':'10.00','remaining':2,'net':'20.00'},
                'recency':{'scope':'合成；购买与退货是不同事件','purchase':'2020-01-01','return':'2020-01-10','last_purchase':'2020-01-01'},
                'offset_deletion':{'scope':'手算合成；两个事件正负抵消','positive':'20.00','negative':'-20.00','net_before':'0.00','net_after_deleting_both':'0.00','positive_events_before':1,'positive_events_after':0}}}


def main():
    path=ROOT/'data/online_retail_ii.csv';spec=load_sources()['retail']['files'][0]
    verify_file(path,spec)
    result=probe(path);result['input_sha256']=spec['sha256']
    output=ROOT/'reports/q1_3_rule_probe.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(output)


if __name__=='__main__':
    main()
