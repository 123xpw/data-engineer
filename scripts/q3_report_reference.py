"""验证端直接读Arrow，用Python排序与fsum复算报告，不调用生产汇总。"""
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import pyarrow.parquet as pq

NUMERIC={'sales_facts':['quantity','unit_price','total_amount'],
         'customer_features':['recency_days','frequency','monetary','unique_products'],
         'returns_log':['quantity','unit_price','total_amount']}


def require(condition,message):
    if not condition:raise AssertionError(message)


def close(actual,expected,field):
    if expected is None:require(actual is None,'空值统计应为null：'+field);return
    require(type(actual) in (float,int) and math.isfinite(actual),'统计类型/非有限错误：'+field)
    require(math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-12),'统计复算不符：'+field)


def quantile(sorted_values,fraction):
    position=(len(sorted_values)-1)*fraction;lower=position.numerator//position.denominator
    upper=(position.numerator+position.denominator-1)//position.denominator
    return sorted_values[lower]+(sorted_values[upper]-sorted_values[lower])*float(position-lower)


def check_frame_statistics(table,claim,numeric_columns):
    require(isinstance(claim,dict),'输出统计不是对象');n=table.num_rows
    require(type(claim.get('rows')) is int and claim['rows']==n,'输出行数不符')
    for kind in ('null_counts','null_rates'):
        require(isinstance(claim.get(kind),dict) and set(claim[kind])==set(table.column_names),'逐列空值统计缺项')
    for name in table.column_names:
        count=table[name].null_count;actual=claim['null_counts'][name]
        require(type(actual) is int and actual==count,'空值数量不符：'+name)
        rate=claim['null_rates'][name];require(rate is None if not n else type(rate) is float,'空值率类型或空分母错误')
        close(rate,count/n if n else None,'null_rate.'+name)
    require(isinstance(claim.get('numeric_distributions'),dict) and set(claim['numeric_distributions'])==set(numeric_columns),'数值分布缺项')
    for name in numeric_columns:
        values=[x for x in table[name].to_pylist() if x is not None]
        require(all(type(v) in (int,float) and math.isfinite(v) for v in values),'输出数值有非有限值')
        values.sort();expected={'count':len(values),'min':None,'p50':None,'p95':None,'max':None,'mean':None}
        if values:expected.update(min=values[0],max=values[-1],p50=quantile(values,Fraction(1,2)),
                                  p95=quantile(values,Fraction(19,20)),mean=math.fsum(values)/len(values))
        actual=claim['numeric_distributions'][name];require(set(actual)==set(expected),'数值统计字段缺项')
        require(type(actual['count']) is int and actual['count']==expected['count'],'有效数不符')
        for key in ('min','p50','p95','max','mean'):close(actual[key],expected[key],name+'.'+key)
    counts=Counter(table['country'].to_pylist())
    countries=[{'value':value,'rows':count} for value,count in counts.items()]
    countries.sort(key=lambda r:(-r['rows'],r['value'] is not None,r['value'] or ''))
    actual=claim.get('country_distribution')
    require(isinstance(actual,list) and all(isinstance(r,dict) and set(r)=={'value','rows'} and type(r['rows']) is int for r in actual),'国家桶字段/类型缺项')
    require(actual==countries and sum(r['rows'] for r in actual)==n,'国家分布或覆盖不符')
    return {'rows':n,'all_column_null_counts_and_rates_verified':True,'numeric_columns':numeric_columns,
            'country_buckets':len(countries),'country_coverage':sum(counts.values())}


def check_report_statistics(folder,report=None):
    folder=Path(folder);path=folder/'validation_metrics.json'
    report=json.loads(path.read_text()) if report is None else report
    require(report.get('statistics_policy')=={'null_rate_denominator':'each_output_rows','empty_rate':None,'quantile_interpolation':'linear'},'统计口径缺失或改变')
    require(isinstance(report.get('outputs'),dict) and set(report['outputs'])==set(NUMERIC),'输出统计范围缺项')
    results={name:check_frame_statistics(pq.read_table(folder/'outputs'/(name+'.parquet')),report['outputs'][name],columns)
             for name,columns in NUMERIC.items()}
    return {'outputs':results,'metric_file_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'method':'Arrow原生读取；Python排序、Fraction位置及math.fsum；不调用生产汇总',
            'numeric_tolerance':{'relative':1e-12,'absolute':1e-12},
            'scope':'实际Parquet的报告统计，不认证清洗政策、真实退款或全仓文档语义质量'}
