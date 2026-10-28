"""独立验证补证实验：pandas/整数金额；不导入实验统计代码。"""

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from verification_support import ROOT, EvidenceRun, sha256
from verify_q1_1 import test_suite


def verify_independently(path, result, mapping):
    f=pd.read_csv(path,dtype=str,keep_default_na=False,na_filter=False,skip_blank_lines=False,encoding='utf-8-sig')
    q=f.Quantity.astype('int64')
    converted={p:Decimal(p)*1000 for p in f.Price.unique()}
    assert all(p==p.to_integral_value() for p in converted.values()), '参考引擎假定本版本最多三位小数；不能截断'
    p=f.Price.map({s:int(v) for s,v in converted.items()}).astype('int64')
    a=q*p
    normal=f.StockCode.str.fullmatch('[0-9]+[A-Za-z]*')
    numeric=f.Invoice.str.fullmatch('[0-9]+')
    keep=normal & numeric & q.gt(0) & p.gt(0)
    excluded=normal & f.Invoice.str.startswith('C') & q.lt(0) & p.gt(0)
    expected_decision=np.select([keep,excluded],['candidate_keep','exclude_positive_basket'],default='pending')
    quantity_sign=np.select([q.lt(0),q.gt(0)],['negative','positive'],default='zero')
    price_sign=np.select([p.lt(0),p.gt(0)],['negative','positive'],default='zero')
    fallback=pd.Series(np.where(numeric,'numeric','other_invoice'))+'__q_'+quantity_sign+'__p_'+price_sign
    reasons=np.select([~normal,keep,excluded],['special_code','numeric_positive','c_negative'],default=fallback.to_numpy(dtype=str))
    f=f.assign(amount=a,quantity=q,selected=np.where(keep,a,0),selected_rows=keep.astype(int),
               customer=np.where(f['Customer ID'].eq(''),'missing','present'),decision=expected_decision,reason=reasons)
    tracked=pd.read_csv(mapping,dtype=str,keep_default_na=False)
    assert len(tracked)==len(f)
    assert np.array_equal(tracked.record.astype(int).to_numpy(),np.arange(1,len(f)+1))
    for col in ['Invoice','decision','reason']:
        assert np.array_equal(tracked[col].to_numpy(),f[col].to_numpy()), f'逐记录归属不符：{col}'
    amount_equal=lambda x,n: Decimal(x)==Decimal(int(n))/1000
    assert result['total']['rows']==len(f)
    assert Decimal(result['total']['quantity'])==int(q.sum())
    assert amount_equal(result['total']['net'],a.sum()) and amount_equal(result['total']['absolute'],a.abs().sum())
    assert result['total']['invoices']==f.Invoice.nunique()
    expected_groups=f.groupby(['decision','reason'],sort=True)
    assert {(g['decision'],g['reason']) for g in result['decisions']}==set(expected_groups.groups)
    for g in result['decisions']:
        h=expected_groups.get_group((g['decision'],g['reason']))
        assert g['rows']==len(h) and g['invoices']==h.Invoice.nunique()
        assert Decimal(g['quantity'])==int(h.quantity.sum())
        assert amount_equal(g['net'],h.amount.sum()) and amount_equal(g['absolute'],h.amount.abs().sum())
        digest=hashlib.sha256(''.join(f'{i+1}\n' for i in h.index).encode()).hexdigest()
        assert g['record_numbers_sha256']==digest
    specials=f[~normal]
    assert set(result['special_codes'])==set(specials.StockCode)
    for code,h in specials.groupby('StockCode'):
        assert result['special_codes'][code]['descriptions']==h.Description.value_counts().to_dict()
    def near(actual, expected):
        if expected is None:
            assert actual is None
        else:
            assert actual is not None and abs(actual-expected)<=1e-8,(actual,expected)
    by_invoice=f.groupby(['customer','Invoice']).agg(raw=('amount','sum'),selected=('selected','sum'),rows=('Invoice','size'),selected_rows=('selected_rows','sum'))
    for customer,g in result['decompositions'].items():
        h=by_invoice.loc[customer];survives=h.selected_rows.gt(0)
        n0,n1=int(h.raw.sum()),int(h.selected.sum());d0,d1=len(h),int(survives.sum())
        assert (g['raw_invoices'],g['selected_invoices'],g['raw_rows'],g['selected_rows'])==(d0,d1,int(h.rows.sum()),int(h.selected_rows.sum()))
        assert amount_equal(g['raw_net'],n0) and amount_equal(g['selected_net'],n1) and amount_equal(g['excluded_net'],n0-n1)
        near(g['raw_mean'],n0/1000/d0);near(g['fixed_denominator_mean'],n1/1000/d0)
        near(g['selected_mean'],n1/1000/d1 if d1 else None)
        near(g['numerator_effect'],(n1-n0)/1000/d0)
        near(g['denominator_effect'],n1/1000/d1-n1/1000/d0 if d1 else None)
        partitions={'disappeared':~survives,'retained_amount_changed':survives & h.raw.ne(h.selected),'retained_amount_unchanged':survives & h.raw.eq(h.selected)}
        for name,mask in partitions.items():
            subset=h[mask];v=g['partitions'][name]
            assert v['invoices']==len(subset) and amount_equal(v['raw_net'],subset.raw.sum()) and amount_equal(v['selected_net'],subset.selected.sum())
            assert (v['raw_zero'],v['raw_negative'],v['raw_positive'])==(int(subset.raw.eq(0).sum()),int(subset.raw.lt(0).sum()),int(subset.raw.gt(0).sum()))
    def check_distribution(h,v):
        sums=h.groupby('Invoice').amount.sum()
        n=len(sums);net=int(sums.sum())
        assert v['invoices']==n and amount_equal(v['net'],net)
        near(v['mean'],net/1000/n if n else None)
        for name,quantile in [('median',.5),('p90',.9)]:
            near(v[name],float(sums.quantile(quantile))/1000 if n else None)
        ordered=sums.rename('amount').reset_index().sort_values(['amount','Invoice'],ascending=[False,True])
        count=int(np.ceil(n*.01));removed=ordered.head(count);tail=ordered.iloc[count:]
        assert v['removed_top_count']==count and amount_equal(v['removed_top_net'],removed.amount.sum())
        near(v['trimmed_mean'],int(tail.amount.sum())/1000/len(tail) if len(tail) else None)
    selected=f[keep].copy()
    for customer,v in result['global_candidate_distributions'].items():
        check_distribution(selected[selected.customer.eq(customer)],v)
    selected['month']=selected.InvoiceDate.str.slice(0,7)
    for axis,column in [('country','Country'),('month','month')]:
        assert set(result['layers'][axis])==set(selected[column])
        for label,groups in result['layers'][axis].items():
            for customer,v in groups.items():
                h=selected[selected[column].eq(label) & selected.customer.eq(customer)]
                assert v['rows']==len(h)
                check_distribution(h,v)
        assert result['cross_layer_invoices'][axis]==int(selected.groupby('Invoice')[column].nunique().gt(1).sum())
    assert result['mixed_identity_invoices']==int(f.groupby('Invoice').customer.nunique().gt(1).sum())
    return {'rows':len(f),'individual_decisions_verified':len(tracked),'country_layers':len(result['layers']['country']),
            'month_layers':len(result['layers']['month']),'exact_amounts':True,'mean_quantile_tolerance':1e-8,
            'limitation':'独立计算验证明示规则的影响，不认证业务规则本身'}


def main():
    with EvidenceRun(ROOT/'reports/q1_2','review_validation') as e:
        def units():
            r=test_suite(ROOT,'test*.py')
            assert not r['failures'] and not r['errors'],r
            return r
        if not e.check('手算夹具与既有测试',units):
            return 1
        def generate():
            r=subprocess.run([sys.executable,str(ROOT/'scripts/q1_review_experiments.py')],cwd=ROOT,capture_output=True,text=True,timeout=180)
            assert r.returncode==0,r.stdout[-1500:]
            report=json.loads((ROOT/'reports/q1_2/review_experiment_latest.json').read_text())
            assert report['status']=='passed' and report['source_sha256']==e.report['source_sha256']
            return {'run_id':report['run_id']}
        if not e.check('生成当前源码对应实验产物',generate):
            return 1
        e.check('独立逐记录决策、金额分解与全部分层统计',lambda:verify_independently(ROOT/'data/online_retail_ii.csv',json.loads((ROOT/'reports/q1_2_review_metrics.json').read_text()),ROOT/'.venv/q1-review/decisions.csv'))
        def regression():
            r=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q1_2.py')],cwd=ROOT,capture_output=True,text=True,timeout=360)
            assert r.returncode==0,r.stdout[-1500:]
            report=json.loads((ROOT/'reports/q1_2/acceptance_latest.json').read_text())
            assert report['status']=='passed' and report['source_sha256']==e.report['source_sha256']
            return {'run_id':report['run_id'],'scope':'旧计算检查回归，包含 Q1.1 与骨架；不作为业务放行'}
        e.check('已有计算回归及输入不变',regression)
        e.report['business_release']='pending_evidence'
        e.report['artifact_sha256']={str(p.relative_to(ROOT)):sha256(p) for p in [ROOT/'reports/q1_2_review_metrics.json',ROOT/'reports/q1_2_review_results.md']}
        e.save()
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
