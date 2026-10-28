"""独立于生产统计的口径消融实验；研究条件变化，不推断客户身份。"""

import csv
from decimal import Decimal
from pathlib import Path
import re

from verification_support import EvidenceRun, ROOT, sha256


def experiment(path):
    # 分别改变单一条件，再按累积条件观察；不能把多个过滤条件的影响混在一起解释。
    names = ['raw', 'positive_quantity_only', 'positive_price_only', 'numeric_invoice_only',
             'ordinary_code_only', 'positive_quantity_and_price', 'positive_and_numeric_invoice', 'candidate']
    views = {name:{g:{'rows':0,'net':Decimal(0),'invoices':set()} for g in ['missing','present']} for name in names}
    with Path(path).open(newline='',encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            q,p = Decimal(row['Quantity']),Decimal(row['Price'])
            numeric = bool(re.fullmatch('[0-9]+',row['Invoice']))
            ordinary = bool(re.fullmatch('[0-9]+[A-Za-z]*',row['StockCode']))
            flags = [True,q>0,p>0,numeric,ordinary,q>0 and p>0,q>0 and p>0 and numeric,q>0 and p>0 and numeric and ordinary]
            group = 'missing' if row['Customer ID']=='' else 'present'
            for name,include in zip(names,flags):
                if include:
                    v=views[name][group]; v['rows']+=1; v['net']+=q*p; v['invoices'].add(row['Invoice'])
    result={}
    for name,groups in views.items():
        result[name]={}
        for g,v in groups.items():
            n=len(v['invoices'])
            result[name][g]={'rows':v['rows'],'net':str(v['net']),'invoices':n,
                             'invoice_mean':str(v['net']/n) if n else None}
    return result


def main():
    path=ROOT/'data/online_retail_ii.csv'
    with EvidenceRun(ROOT/'reports/q1_2','sensitivity') as evidence:
        def run():
            before=sha256(path)
            result=experiment(path)
            assert sha256(path)==before, '输入被修改'
            return {'input_sha256':before,'views':result,
                    'meaning':'均额为组内所选明细净额/这些明细的不同发票数；每步分母会变化。单条件与累积条件是描述性比较，不是因果实验。'}
        if evidence.check('逐条件消融：匿名群体均额是否稳健',run):
            views=evidence.report['checks'][-1]['evidence']['views']
            labels=['不筛选','仅正数量','仅正单价','仅纯数字发票','仅常规编码','正数量且正单价','前项再限纯数字发票','前项再限常规编码（候选销售）']
            lines=['# Q1.2 客户均额的口径消融实验','',
                   '来源：冻结的原始 CSV；独立标准库 CSV + Decimal 逐行统计，不调用生产模块。脚本为 scripts/experiment_q1_2_sensitivity.py。',
                   '前四个“仅”条件分别从原始全集开始；后三项累积过滤。均额分母是每个视图实际保留的不同发票数。','',
                   '| 条件 | 缺失组行数 | 发票数 | 发票均额 £ | 非缺失组行数 | 发票数 | 发票均额 £ |','|---|---:|---:|---:|---:|---:|---:|']
            for label,g in zip(labels,views.values()):
                a,b=g['missing'],g['present']
                lines.append(f"| {label} | {a['rows']} | {a['invoices']} | {Decimal(a['invoice_mean']):.6f} | {b['rows']} | {b['invoices']} | {Decimal(b['invoice_mean']):.6f} |")
            lines += ['', '观察：只保留正数量，或只保留正单价，就已经使两组均额的大小关系反转；只保留数字发票或常规编码则未反转。不能把最终反转唯一归因于特殊代码排除，也不能把全部差异归因于坏账。', '',
                      '这不是随机对照因果实验：金额分子与发票分母一起改变，记录是否被筛掉也与原有业务有关。它只证明群体画像对统计口径敏感；不证明缺失客户的消费能力或渠道。正式客单价需要先确认订单粒度、交易状态及商品主数据。','']
            (ROOT/'reports/q1_2_sensitivity.md').write_text('\n'.join(lines),encoding='utf-8')
    print(evidence.path)
    return 0 if evidence.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
