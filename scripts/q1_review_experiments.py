"""Q1.2 补证：规则影响账、均额分解和预定分层；不执行业务清洗。"""

from collections import Counter, defaultdict
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from download_data import load_sources, verify_file
from scripts.verification_support import EvidenceRun, sha256


def distribution(invoices):
    """明细先聚合到发票；分位数线性插值，大额剔除仅作敏感性。"""
    ordered=sorted(invoices.items(),key=lambda kv:(-kv[1],kv[0]))
    n=len(ordered); removed=(n+99)//100
    values=sorted(invoices.values()); net=sum(values,Decimal(0))
    def quantile(p):
        if not n:
            return None
        pos=Fraction(n-1)*p; lower=pos.numerator//pos.denominator
        upper=min(lower+1,n-1)
        return float(Fraction(values[lower])+(Fraction(values[upper])-Fraction(values[lower]))*(pos-lower))
    tail=ordered[removed:]
    return {'invoices':n,'net':str(net),'mean':float(net/n) if n else None,
            'median':quantile(Fraction(1,2)), 'p90':quantile(Fraction(9,10)),
            'removed_top_count':removed,'removed_top_net':str(sum((v for _,v in ordered[:removed]),Decimal(0))),
            'trimmed_mean':float(sum((v for _,v in tail),Decimal(0))/len(tail)) if tail else None}


def analyze(path, mapping_path=None):
    """逐行 Decimal 计算；决策仅针对正向购物篮候选。"""
    invoices=defaultdict(lambda:defaultdict(lambda:{'raw':Decimal(0),'selected':Decimal(0),'rows':0,'selected_rows':0}))
    groups=defaultdict(lambda:{'rows':0,'quantity':Decimal(0),'net':Decimal(0),'absolute':Decimal(0),'invoices':set(),'examples':[],'digest':hashlib.sha256()})
    code_descriptions=defaultdict(Counter)
    layers={axis:defaultdict(lambda:defaultdict(lambda:{'rows':0,'invoices':defaultdict(Decimal)})) for axis in ['country','month']}
    dimensions={axis:defaultdict(set) for axis in layers}
    total_rows=0; total_quantity=Decimal(0); total_net=Decimal(0); total_abs=Decimal(0); all_invoices=set()
    mapping=None
    if mapping_path:
        Path(mapping_path).parent.mkdir(parents=True,exist_ok=True)
        mapping=Path(mapping_path).open('w',newline='',encoding='utf-8')
        writer=csv.writer(mapping); writer.writerow(['record','Invoice','decision','reason'])
    try:
        with localcontext() as context, Path(path).open(newline='',encoding='utf-8-sig') as stream:
            context.prec=50
            for number,row in enumerate(csv.DictReader(stream),1):
                q,p=Decimal(row['Quantity']),Decimal(row['Price']); amount=q*p
                numeric=bool(re.fullmatch('[0-9]+',row['Invoice']))
                ordinary=bool(re.fullmatch('[0-9]+[A-Za-z]*',row['StockCode']))
                selected=numeric and ordinary and q>0 and p>0
                if not ordinary:
                    decision,reason='pending','special_code'
                    code_descriptions[row['StockCode']][row['Description']]+=1
                elif selected:
                    decision,reason='candidate_keep','numeric_positive'
                elif row['Invoice'].startswith('C') and q<0 and p>0:
                    decision,reason='exclude_positive_basket','c_negative'
                else:
                    sign=lambda x:'negative' if x<0 else 'positive' if x>0 else 'zero'
                    decision='pending'; reason=('numeric' if numeric else 'other_invoice')+'__q_'+sign(q)+'__p_'+sign(p)
                g=groups[(decision,reason)]
                g['rows']+=1; g['quantity']+=q; g['net']+=amount; g['absolute']+=abs(amount); g['invoices'].add(row['Invoice'])
                g['digest'].update(f'{number}\n'.encode())
                if len(g['examples'])<3:
                    g['examples'].append({'record':number,**row})
                if mapping:
                    writer.writerow([number,row['Invoice'],decision,reason])
                total_rows+=1;total_quantity+=q;total_net+=amount;total_abs+=abs(amount);all_invoices.add(row['Invoice'])
                customer='missing' if row['Customer ID']=='' else 'present'
                invoice=invoices[customer][row['Invoice']]
                invoice['raw']+=amount;invoice['rows']+=1
                if selected:
                    invoice['selected']+=amount;invoice['selected_rows']+=1
                    for axis,key in [('country',row['Country']),('month',row['InvoiceDate'][:7])]:
                        layer=layers[axis][key][customer];layer['rows']+=1;layer['invoices'][row['Invoice']]+=amount
                        dimensions[axis][row['Invoice']].add(key)
    finally:
        if mapping:
            mapping.close()
    assert sum(g['rows'] for g in groups.values())==total_rows
    for name,value in [('quantity',total_quantity),('net',total_net),('absolute',total_abs)]:
        assert sum((g[name] for g in groups.values()),Decimal(0))==value,name
    union=set().union(*(g['invoices'] for g in groups.values()))
    assert union==all_invoices
    decisions=[]
    for (decision,reason),g in sorted(groups.items()):
        decisions.append({'decision':decision,'reason':reason,'rows':g['rows'],'quantity':str(g['quantity']),
                          'net':str(g['net']),'absolute':str(g['absolute']),'invoices':len(g['invoices']),
                          'record_numbers_sha256':g['digest'].hexdigest(),'examples':g['examples']})
    decompositions={}; global_distributions={}
    for customer,table in sorted(invoices.items()):
        n0=sum((v['raw'] for v in table.values()),Decimal(0));n1=sum((v['selected'] for v in table.values()),Decimal(0))
        d0=len(table);selected={i:v['selected'] for i,v in table.items() if v['selected_rows']};d1=len(selected)
        partitions={k:{'invoices':0,'raw_net':Decimal(0),'selected_net':Decimal(0),'raw_zero':0,'raw_negative':0,'raw_positive':0} for k in ['disappeared','retained_amount_changed','retained_amount_unchanged']}
        for v in table.values():
            key='disappeared' if not v['selected_rows'] else 'retained_amount_changed' if v['raw']!=v['selected'] else 'retained_amount_unchanged'
            g=partitions[key];g['invoices']+=1;g['raw_net']+=v['raw'];g['selected_net']+=v['selected']
            g['raw_negative' if v['raw']<0 else 'raw_positive' if v['raw']>0 else 'raw_zero']+=1
        assert sum(v['invoices'] for v in partitions.values())==d0
        assert sum((v['raw_net'] for v in partitions.values()),Decimal(0))==n0
        assert sum((v['selected_net'] for v in partitions.values()),Decimal(0))==n1
        original=Fraction(n0)/d0;fixed=Fraction(n1)/d0
        selected_mean=Fraction(n1)/d1 if d1 else None
        numerator=(Fraction(n1)-Fraction(n0))/d0
        denominator=Fraction(n1)*(Fraction(1,d1)-Fraction(1,d0)) if d1 else None
        if d1:
            assert selected_mean-original==numerator+denominator
        decompositions[customer]={'raw_rows':sum(v['rows'] for v in table.values()),'selected_rows':sum(v['selected_rows'] for v in table.values()),
            'raw_net':str(n0),'selected_net':str(n1),'excluded_net':str(n0-n1),'raw_invoices':d0,'selected_invoices':d1,
            'raw_mean':float(original),'fixed_denominator_mean':float(fixed),'selected_mean':float(selected_mean) if d1 else None,
            'numerator_effect':float(numerator),'denominator_effect':float(denominator) if d1 else None,
            'exact_identity_verified':bool(d1),'partitions':{k:{a:str(b) if isinstance(b,Decimal) else b for a,b in v.items()} for k,v in partitions.items()}}
        global_distributions[customer]=distribution(selected)
    layer_results={}
    for axis,table in layers.items():
        layer_results[axis]={}
        for label,customers in sorted(table.items()):
            layer_results[axis][label]={}
            for customer in ['missing','present']:
                g=customers.get(customer,{'rows':0,'invoices':{}})
                layer_results[axis][label][customer]={'rows':g['rows'],**distribution(g['invoices'])}
        assert sum(v['rows'] for customers in table.values() for v in customers.values())==sum(v['selected_rows'] for v in decompositions.values())
        assert sum((amount for customers in table.values() for v in customers.values() for amount in v['invoices'].values()),Decimal(0))==sum((Decimal(v['selected_net']) for v in decompositions.values()),Decimal(0))
    return {'total':{'rows':total_rows,'quantity':str(total_quantity),'net':str(total_net),'absolute':str(total_abs),'invoices':len(all_invoices)},
            'decisions':decisions,'decision_invoice_sum':sum(g['invoices'] for g in decisions),'decision_invoice_union':len(union),
            'special_codes':{code:{'status':'缺少商品主数据确认；不得仅凭格式删除','descriptions':dict(sorted(counts.items()))} for code,counts in sorted(code_descriptions.items())},
            'decompositions':decompositions,'global_candidate_distributions':global_distributions,'layers':layer_results,
            'cross_layer_invoices':{axis:sum(len(s)>1 for s in table.values()) for axis,table in dimensions.items()},
            'mixed_identity_invoices':len(set(invoices['missing']) & set(invoices['present']))}


def render(result):
    fmt=lambda x:'不适用' if x is None else f'{x:.6f}'
    lines=['# Q1.2 补证实验结果','',
           '本轮实验回答规则影响和均额口径问题；没有确认客户身份或商品主数据。脚本：scripts/q1_review_experiments.py；机器指标：q1_2_review_metrics.json。', '',
           '## A：候选规则影响账','',
           '用途限定为正向商品购物篮候选。候选保留不是已确认商品；排除只指不进入正向购物篮，取消/贷项仍保留在原始账中；待确认不自动删除。逐记录归属保存在本地忽略目录 .venv/q1-review/decisions.csv，可重跑生成。','',
           '| 决策 | 原因 | 记录数 | 数量合计 | 净额 | 绝对金额 | 不同发票 |','|---|---|---:|---:|---:|---:|---:|']
    for g in result['decisions']:
        lines.append(f"| {g['decision']} | {g['reason']} | {g['rows']} | {g['quantity']} | {g['net']} | {g['absolute']} | {g['invoices']} |")
    lines += ['',f"全体 {result['total']['rows']} 条记录、{result['total']['invoices']} 张发票；各原因发票数直接相加为 {result['decision_invoice_sum']}，集合并集为 {result['decision_invoice_union']}。差异来自同一发票跨类别，不能直接相加。",'',
              f"全部 {len(result['special_codes'])} 个特殊代码的描述和未确认状态见机器指标；完整的原始解释仍需证据评审，数值对账不认证业务含义。",'',
              '## B：分子与分母分开','',
              '| 客户 ID | 原发票数 | 候选发票数 | 原均额 | 固定原分母后的均额 | 候选均额 | 分子变化贡献 | 分母变化贡献 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for group,g in result['decompositions'].items():
        lines.append(f"| {group} | {g['raw_invoices']} | {g['selected_invoices']} | {fmt(g['raw_mean'])} | {fmt(g['fixed_denominator_mean'])} | {fmt(g['selected_mean'])} | {fmt(g['numerator_effect'])} | {fmt(g['denominator_effect'])} |")
    lines += ['', '贡献按预先规定的分解路径计算，有理数精确对账；不是唯一的因果贡献分配。固定分母均额只是诊断量，不是正式客单价。','',
              '| 客户 ID | 发票去向 | 发票数 | 原净额 | 候选净额 | 原额零/负/正发票数 |','|---|---|---:|---:|---:|---|']
    for group,g in result['decompositions'].items():
        for name,p in g['partitions'].items():
            lines.append(f"| {group} | {name} | {p['invoices']} | {p['raw_net']} | {p['selected_net']} | {p['raw_zero']}/{p['raw_negative']}/{p['raw_positive']} |")
    lines += ['', '## C：分层与最高 1% 发票敏感性','',
              '分位数为线性插值。移除数取 ceil(n×1%)，并列按发票字符串升序；仅诊断，不删原始数据。空组与移除后空组均显示不适用。小样本不作为稳定群体证据。','']
    def table(label,rows):
        output=[f'### {label}','','| 层 | ID 组 | 发票数 | 均值 | 中位数 | P90 | 移除数 | 移除金额 | 移除后均值 |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
        for layer,groups in rows.items():
            for group,v in groups.items():
                output.append(f"| {layer} | {group} | {v['invoices']} | {fmt(v['mean'])} | {fmt(v['median'])} | {fmt(v['p90'])} | {v['removed_top_count']} | {v['removed_top_net']} | {fmt(v['trimmed_mean'])} |")
        return output+['']
    lines += table('全部候选发票',{'all':result['global_candidate_distributions']})
    for axis,rows in result['layers'].items():
        lines += table(axis,rows)
        lines += [f"该维度跨层发票数：{result['cross_layer_invoices'][axis]}。分层金额与明细行数已加回整体；不能默认分层发票数可相加。",'']
    lines += ['## 决策状态','','计算证据由独立验证器核验，报告生成成功本身不代表通过。业务证据仍不足以确认匿名身份、全部代码类型和取消原因；候选规则暂不批准为通用清洗策略。结果中的排序和差异都只描述本次冻结数据与明示口径。','']
    return '\n'.join(lines)


def main():
    with EvidenceRun(ROOT/'reports/q1_2','review_experiment') as e:
        def run():
            path=ROOT/'data/online_retail_ii.csv';expected=load_sources()['retail']['files'][0]
            verify_file(path,expected)
            mapping=ROOT/'.venv/q1-review/decisions.csv'
            result=analyze(path,mapping)
            assert sha256(path)==expected['sha256']
            output=ROOT/'reports/q1_2_review_metrics.json';output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
            report=ROOT/'reports/q1_2_review_results.md';report.write_text(render(result))
            return {'input_sha256':expected['sha256'],'metrics_sha256':sha256(output),'report_sha256':sha256(report),'mapping_sha256':sha256(mapping),
                    'scope':'仅内部对账；独立计算核验另运行 verify_q1_review.py；业务放行待确认'}
        e.check('A/B/C 原始数据计算及内部对账',run)
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
