"""从原始数据重新核验已实现部分的控制数；不读取旧 passed 结论。"""

from collections import Counter
import csv
from decimal import Decimal as D,localcontext,ROUND_HALF_UP
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def require(condition,message):
    if not condition:
        raise ValueError(message)


def main():
    audit=json.loads((ROOT/'reports/project_audit/latest.json').read_text())
    out=ROOT/'reports/project_audit'/audit['run_id']
    result={'scope':'Q1.1 基础统计与 Q2.1/Q2.2 全量控制数，不认证 Q1.2/Q1.3 的全部业务解释',
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checks':[],'status':'running'}
    def save():
        (out/'controls.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    save()
    try:
        manifest=json.loads((ROOT/'data_sources.json').read_text())
        result['input_sha256']={}
        for dataset in manifest['datasets'].values():
            for f in dataset['files']:
                h=hashlib.sha256((ROOT/'data'/f['target']).read_bytes()).hexdigest()
                require(h==f['sha256'],'输入偏离冻结版本')
                result['input_sha256'][f['target']]=h
        with tempfile.TemporaryDirectory(prefix='gekko-control-audit-') as folder:
            temp=Path(folder)
            for name,command in [
                ('quality',[str(ROOT/'q1_data_quality/q1_code.py'),'--input',str(ROOT/'data/online_retail_ii.csv')]),
                ('translation',[str(ROOT/'q2_sql_analysis/q2_1.py'),'--skip-load']),
                ('monthly',[str(ROOT/'q2_sql_analysis/q2_2.py'),'--skip-load'])]:
                run=subprocess.run([sys.executable,*command,'--output-dir',str(temp)],cwd=temp,capture_output=True,text=True,timeout=120)
                require(run.returncode==0,f'{name} 实际入口失败')
            quality=json.loads((temp/'data_quality_metrics.json').read_text())
            fields=quality['columns'];counts={k:Counter() for k in fields if k not in ('Quantity','Price')}
            missing=Counter();nums={k:{'n':0,'sum':D(0),'ss':D(0),'min':None,'max':None} for k in ('Quantity','Price')}
            n=0
            with localcontext() as ctx:
                ctx.prec=40
                with (ROOT/'data/online_retail_ii.csv').open(encoding='utf-8-sig',newline='') as stream:
                    for row in csv.DictReader(stream):
                        n+=1
                        for col,value in row.items():
                            if not value:missing[col]+=1
                            elif col in counts:counts[col][value]+=1
                            else:
                                v=D(value);require(v.is_finite(),'控制数遇到非有限数字')
                                s=nums[col];s['n']+=1;s['sum']+=v;s['ss']+=v*v
                                s['min']=v if s['min'] is None else min(s['min'],v)
                                s['max']=v if s['max'] is None else max(s['max'],v)
                require(quality['rows']==n,'Q1 行数错误')
                for col,item in fields.items():
                    require(item['missing_count']==missing[col],f'{col} 缺失计数错误')
                    require(math.isclose(item['missing_fraction'],missing[col]/n,abs_tol=1e-14),f'{col} 缺失比例错误')
                    if col in counts:
                        ranked=sorted(counts[col].items(),key=lambda p:(-p[1],p[0]))[:10]
                        require(item['top10']==[{'value':v,'count':c} for v,c in ranked],f'{col} 高频排序错误')
                        require(item['unique_nonempty']==len(counts[col]),f'{col} 唯一数错误')
                    else:
                        s=nums[col];mean=s['sum']/s['n'];std=((s['ss']-s['sum']**2/s['n'])/(s['n']-1)).sqrt()
                        for key,expected in {'min':s['min'],'max':s['max'],'mean':mean,'std':std}.items():
                            require(math.isclose(item['numeric'][key],float(expected),rel_tol=1e-10,abs_tol=1e-10),f'{col}.{key} 分布错误')
            result['checks'].append({'name':'Q1.1 CSV/Counter/Decimal 全量控制数','matched':True,'rows':n,'missing_customer':missing['Customer ID']});save()
            base=ROOT/'data/olist'
            products=pd.read_csv(base/'olist_products_dataset.csv',dtype=str,keep_default_na=False)
            translation=pd.read_csv(base/'product_category_name_translation.csv',dtype=str,keep_default_na=False)
            valid=set(translation.loc[translation.product_category_name_english.str.strip(' ').ne(''),'product_category_name'])
            freq=products.product_category_name.value_counts().to_dict()
            expected=[{'category':key,'products':value} for key,value in sorted(freq.items()) if key and key not in valid]
            actual=json.loads((temp/'q2_1_results.json').read_text())
            require(actual['named_translation_gaps']==expected and actual['unknown_category_products']==freq.get('',0),'Q2.1 控制数错误')
            result['checks'].append({'name':'Q2.1 原始数据反连接控制数','matched':True,'gaps':expected,'unknown_category':freq.get('',0)});save()
            orders=pd.read_csv(base/'olist_orders_dataset.csv',dtype=str,keep_default_na=False)
            items=pd.read_csv(base/'olist_order_items_dataset.csv',dtype=str,keep_default_na=False)
            # 逐项确认最小货币单位可精确表示，再转换整数；不能先舍入掩盖三位小数。
            for column in ('price','freight_value'):
                values=[D(x)*100 for x in items[column]]
                require(all(x==int(x) for x in values),'当前 Olist 金额不能按整数分无损表示')
                items[column]=[int(x) for x in values]
            items['cents']=items.price+items.freight_value
            per_order=items.groupby('order_id',as_index=False).cents.sum()
            joined=orders.merge(per_order,on='order_id',how='left',validate='one_to_one')
            joined['month']=joined.order_purchase_timestamp.str[:7]
            durations=pd.to_datetime(joined.order_delivered_customer_date.replace('',None))-pd.to_datetime(joined.order_purchase_timestamp)
            joined['seconds']=durations.dt.total_seconds()
            actual=json.loads((temp/'q2_2_results.json').read_text())['months']
            expected=[]
            for month,g in joined.groupby('month',sort=True):
                d=g[g.order_status.eq('delivered')];secs=d.seconds.dropna().astype('int64')
                require(d.cents.notna().all(),'delivered 缺金额')
                cancel=int(g.order_status.eq('canceled').sum())
                expected.append({'month':month,'total_orders':len(g),'delivered_orders':len(d),'canceled_orders':cancel,
                    'cancel_rate':str((D(cancel)*100/len(g)).quantize(D('.01'),rounding=ROUND_HALF_UP)),
                    'delivered_gmv':str((D(int(d.cents.sum()))/100).quantize(D('.001'))),
                    'avg_delivery_days':str((D(int(secs.sum()))/(len(secs)*86400)).quantize(D('.000001'),rounding=ROUND_HALF_UP)) if len(secs) else None,
                    'valid_delivery_orders':len(secs),'missing_delivery_time_orders':len(d)-len(secs)})
            wanted_keys=list(expected[0]);observed=[{k:r[k] for k in wanted_keys} for r in actual]
            require(observed==expected,'Q2.2 月份、指标或有效时长分母不符')
            result['checks'].append({'name':'Q2.2 pandas 按订单聚合/整数分控制数','matched':True,'months':len(expected),'orders':len(orders),
                'gmv':str(sum(D(r['delivered_gmv']) for r in expected)),'missing_time':sum(r['missing_delivery_time_orders'] for r in expected)});save()
            for filename in ('data_quality_metrics.json','q2_1_results.json','q2_2_results.json'):
                (out/('fresh_'+filename)).write_bytes((temp/filename).read_bytes())
        result['status']='controls_match';save()
    except Exception as exc:
        result['status']='controls_failed';result['error']=type(exc).__name__+': '+str(exc);save();raise
    print(json.dumps(result['checks'],ensure_ascii=False))
    print(out/'controls.json')


if __name__=='__main__':
    main()
