"""CSV/Decimal 独立参考：逐行摘要、客户集合、列表删除匹配；不导入生产函数。"""
from bisect import bisect_left
from collections import Counter,defaultdict
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
EXCEPTIONS=set('PADS SP1002 DCGS0003 DCGS0004 DCGS0037 DCGS0041 DCGS0044 DCGS0058 DCGS0062 DCGS0066N DCGS0068 DCGS0069 DCGS0070 DCGS0072 DCGS0075 DCGS0076 DCGSSBOY DCGSSGIRL'.split())
FEES=set('ADJUST ADJUST2 AMAZONFEE B C2 CRUK D DOT POST'.split())|{'BANK CHARGES'}


def check(folder):
    started=time.perf_counter();folder=Path(folder)
    expected_hash=hashlib.sha256();actual_hash=hashlib.sha256();reasons=Counter();customers={};candidates=defaultdict(list);return_events=[];latest=None;amount=0;sales_count=0
    def digest_row(h,row):h.update((json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode())
    with (ROOT/'data/online_retail_ii.csv').open(newline='',encoding='utf-8-sig') as stream:
        for source,r in enumerate(csv.DictReader(stream),1):
            invoice,stock=r['Invoice'],r['StockCode'];quantity=int(r['Quantity']);price=int(Decimal(r['Price'])*1000)
            when=datetime.strptime(r['InvoiceDate'],'%Y-%m-%d %H:%M:%S');latest=max(latest,when) if latest else when
            code=stock.strip();customer=r['Customer ID'];value=quantity*price
            if invoice.startswith('C'):reason='cancel_event';return_events.append((when,source,invoice,customer,stock,quantity,price))
            elif not invoice.isascii() or not invoice.isdecimal():reason='non_numeric_invoice'
            elif quantity<=0:reason='nonpositive_quantity'
            elif price<=0:reason='nonpositive_price'
            elif code in FEES or code.startswith(('gift_','TEST')):reason='nonproduct'
            elif not re.fullmatch('[0-9]+[a-z]*',code,re.IGNORECASE) and code not in EXCEPTIONS:reason='pending_product'
            else:reason='retained'
            reasons[reason]+=1
            if reason!='retained':continue
            sales_count+=1;amount+=value
            digest_row(expected_hash,[source,invoice,stock,r['Description'],quantity,price,value,r['InvoiceDate'],customer or None,r['Country']])
            if customer:
                state=customers.setdefault(customer,{'invoices':set(),'products':set(),'first':when,'last':when,'amount':0,'countries':defaultdict(set)})
                state['invoices'].add(invoice);state['products'].add(stock);state['first']=min(state['first'],when);state['last']=max(state['last'],when);state['amount']+=value;state['countries'][r['Country']].add(invoice)
                candidates[(customer,stock,quantity)].append((when,source,invoice,price))
    for key,group in candidates.items():group.sort()
    first_time={key:group[0][0] for key,group in candidates.items()};same_time={key:Counter(r[0] for r in group) for key,group in candidates.items()}
    matched={};match_counts=Counter()
    for when,source,invoice,customer,stock,quantity,price in sorted(return_events):
        selected=None;ties=0
        if quantity>=0:reason='unexpected_nonnegative_cancel_quantity'
        elif not customer:reason='missing_customer'
        elif (customer,stock,-quantity) not in candidates:reason='no_exact_quantity_candidate'
        else:
            key=(customer,stock,-quantity);group=candidates[key];position=bisect_left(group,(when,-1))-1
            if position<0:reason='eligible_candidates_consumed' if first_time[key]<when else 'no_strictly_earlier_sale'
            else:selected=group.pop(position);reason='candidate_matched';ties=same_time[key][selected[0]]
        match_counts[reason]+=1
        # 未选中候选时不进行比较；选中后直接比较 CSV 独立解析的整数价格。
        price_comparison=None
        if selected is not None:price_comparison=selected[3]!=price
        matched[source]={'invoice':selected[2] if selected else None,'source':selected[1] if selected else None,'reason':reason,'ties':ties,'price_mismatch':price_comparison}
    sales=pd.read_parquet(folder/'outputs/sales_facts.parquet')
    for r in sales.itertuples(index=False):
        digest_row(actual_hash,[r.source_row,r.invoice_no,r.stock_code,r.description,r.quantity,round(r.unit_price*1000),round(r.total_amount*1000),r.invoice_datetime.strftime('%Y-%m-%d %H:%M:%S'),None if pd.isna(r.customer_id) else r.customer_id,r.country])
    if len(sales)!=sales_count or expected_hash.hexdigest()!=actual_hash.hexdigest():raise AssertionError('销售归属/顺序/全部字段或金额不符 CSV 独立参考')
    features=pd.read_parquet(folder/'outputs/customer_features.parquet')
    if len(features)!=len(customers):raise AssertionError('客户覆盖不一致')
    for row in features.itertuples(index=False):
        expected=customers[row.customer_id]
        country=sorted(expected['countries'],key=lambda x:(-len(expected['countries'][x]),x))[0]
        values=(row.frequency,row.unique_products,row.recency_days,round(row.monetary*1000),row.country,row.is_one_time_buyer,row.first_purchase_date.to_pydatetime(),row.last_purchase_date.to_pydatetime())
        wanted=(len(expected['invoices']),len(expected['products']),(latest.date()-expected['last'].date()).days,expected['amount'],country,len(expected['invoices'])==1,expected['first'],expected['last'])
        if values!=wanted:raise AssertionError('客户特征逐列不符独立集合参考')
    returns=pd.read_parquet(folder/'outputs/returns_log.parquet')
    if len(returns)!=len(return_events):raise AssertionError('取消日志行数不符')
    if str(returns['price_mismatch'].dtype)!='boolean':raise AssertionError('价格比较未保留可空布尔类型')
    for row in returns.itertuples(index=False):
        expected=matched[row.source_row]
        actual_comparison=None if pd.isna(row.price_mismatch) else bool(row.price_mismatch)
        values=(None if pd.isna(row.matched_original_invoice) else row.matched_original_invoice,None if pd.isna(row.matched_source_row) else int(row.matched_source_row),row.match_reason,row.same_time_candidate_rows,actual_comparison)
        wanted=(expected['invoice'],expected['source'],expected['reason'],expected['ties'],expected['price_mismatch'])
        if values!=wanted:raise AssertionError('退货候选/容量/原因逐条不符独立列表删除参考')
    metrics=json.loads((folder/'validation_metrics.json').read_text())
    if metrics['reason_counts']!=dict(reasons) or metrics['match_reasons']!=dict(match_counts) or metrics['sales_amount_milli']!=amount:raise AssertionError('报告与独立复算不一致')
    price_counts=dict(Counter('unknown' if r['price_mismatch'] is None else 'different' if r['price_mismatch'] else 'same' for r in matched.values()))
    price_counts={key:price_counts.get(key,0) for key in ('unknown','same','different')}
    if metrics.get('price_comparison_counts')!=price_counts:raise AssertionError('价格比较分母与独立原始价格参考不一致')
    if metrics['return_candidate_sensitivity']['matched_price_mismatch_rows']!=price_counts['different']:raise AssertionError('已匹配价格差异计数不符')
    return {'sales_rows':sales_count,'customers':len(customers),'returns':len(return_events),'sales_amount_milli':amount,
        'sales_row_digest':actual_hash.hexdigest(),'all_customer_fields_compared':True,'all_return_choices_compared':True,
        'reason_counts':dict(reasons),'match_reasons':dict(match_counts),'price_comparison_counts':price_counts,'seconds':round(time.perf_counter()-started,6),
        'limits':'政策例外清单由同一 Q1 解释导出，算法独立但业务政策仍需复核；参考性能不计入生产 120 秒'}


if __name__=='__main__':
    result=check(sys.argv[1] if len(sys.argv)>1 else ROOT/'.venv/q3-candidate')
    print(json.dumps(result,ensure_ascii=False))
