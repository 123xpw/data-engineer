"""Q1.3 文档交付与反例证据检查；不自动判定业务语义正确。"""

from decimal import Decimal
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pandas as pd

from verification_support import EvidenceRun, ROOT, sha256


def main():
    with EvidenceRun(ROOT/'reports/q1_3','acceptance') as e,tempfile.TemporaryDirectory(prefix='gekko-q13-') as folder:
        temp=Path(folder)
        docs=['cleaning_strategy.md','strategy_review.md']
        e.report['document_sha256']={name:sha256(ROOT/'q1_data_quality'/name) for name in docs};e.save()
        def cli(args,expected=0,cwd=temp,timeout=180):
            r=subprocess.run([sys.executable,*map(str,args)],cwd=cwd,capture_output=True,text=True,timeout=timeout)
            assert r.returncode==expected,f'预期 {expected}，实际 {r.returncode}：{r.stdout[-800:]}'
            return r
        def documents():
            direct=temp/'direct';combined=temp/'combined'
            r=cli([ROOT/'q1_data_quality/q1_strategy.py','--output-dir',direct])
            claim=json.loads(r.stdout)
            cli([ROOT/'run_all.py','--stage','q1.3','--q1-output-dir',combined,'--report',temp/'entry.json'])
            entries=json.loads((temp/'entry.json').read_text())['results']
            assert len(entries)==1 and entries[0]['stage']=='q1.3' and entries[0]['status']=='passed'
            assert entries[0]['detail']==claim
            for name in docs:
                assert (direct/name).read_bytes()==(combined/name).read_bytes()==(ROOT/'q1_data_quality'/name).read_bytes()
                assert sha256(direct/name)==e.report['document_sha256'][name]
            body=(direct/'cleaning_strategy.md').read_text().partition('\n')[2]
            count=sum(not ch.isspace() for ch in body)
            assert 300<=count<=500 and count==claim['nonwhitespace_characters']
            assert '未获得' in claim['business_approval']
            return {'nonwhitespace_characters':count,'han_characters':claim['han_characters'],'scope':'仅交付协议及字数；语义审查见 strategy_review.md'}
        e.check('独立/总入口文件一致且正文符合字数',documents)
        def isolation():
            copy=temp/'isolated';(copy/'q1_data_quality').mkdir(parents=True)
            for name in ['run_all.py','download_data.py','artifact_manifest.py']:
                shutil.copyfile(ROOT/name,copy/name)
            for name in [*docs,'q1_strategy.py']:
                shutil.copyfile(ROOT/'q1_data_quality'/name,copy/'q1_data_quality'/name)
            def run(expected):
                cli([copy/'run_all.py','--stage','q1.3','--report',copy/'result.json'],expected=expected)
                result=json.loads((copy/'result.json').read_text())
                assert result['exit_code']==expected
                assert result['results'][0]['status']==('passed' if expected==0 else 'failed')
            run(0)
            (copy/'q1_data_quality/cleaning_strategy.md').write_text('# 标题\n太短\n')
            run(1)
            shutil.copyfile(ROOT/'q1_data_quality/cleaning_strategy.md',copy/'q1_data_quality/cleaning_strategy.md')
            (copy/'q1_data_quality/strategy_review.md').unlink()
            run(1)
            return {'no_data_or_other_q1_module_required':True,'short_document_rejected':True,'missing_review_rejected':True,
                    'limitation':'文件完整不代表内容经业务方认可'}
        e.check('文档入口隔离、缺件和字数越界失败',isolation)
        def counterexample():
            cli([ROOT/'scripts/probe_q1_3_rules.py'])
            result=json.loads((ROOT/'reports/q1_3_rule_probe.json').read_text())
            path=ROOT/'data/online_retail_ii.csv'
            f=pd.read_csv(path,dtype=str,keep_default_na=False,na_filter=False,skip_blank_lines=False)
            group=f[f['Customer ID'].eq('16446.0')]
            records=[{'record':int(i)+1,**row.to_dict()} for i,row in group.iterrows()]
            assert result['records']==records and result['input_sha256']==sha256(path)
            q=group.Quantity.astype(int);p=group.Price.map(Decimal);amount=q*p
            keep=group.Invoice.str.fullmatch('[0-9]+') & group.StockCode.str.fullmatch('[0-9]+[A-Za-z]*') & q.gt(0) & p.gt(0)
            assert Decimal(result['candidate']['gross'])==sum(amount[keep])
            assert result['candidate']['invoices']==group[keep].Invoice.nunique()
            assert result['candidate']['latest_purchase']==group[keep].InvoiceDate.max()
            remaining=keep & q.abs().ne(80995)
            alternative=result['if_extreme_purchase_is_confirmed_cancelled']
            assert Decimal(alternative['gross'])==sum(amount[remaining]) and alternative['invoices']==group[remaining].Invoice.nunique()
            assert alternative['latest_purchase']==group[remaining].InvoiceDate.max()
            assert Decimal(result['pair_net'])==0 and Decimal(result['pair_positive_amount'])==Decimal('168469.60')
            assert result['pair_candidate_rows']==1 and result['pair_time_seconds']==720
            assert Decimal(result['raw_customer_net'])==sum(amount)
            partial=result['synthetic_cases']['partial_return']
            assert (partial['purchased']-partial['returned'])*Decimal(partial['unit_price'])==Decimal(partial['net'])
            assert partial['remaining']==2
            offset=result['synthetic_cases']['offset_deletion']
            assert Decimal(offset['positive'])+Decimal(offset['negative'])==Decimal(offset['net_before'])==Decimal(offset['net_after_deleting_both'])
            assert offset['positive_events_before']!=offset['positive_events_after']
            return {'probe_sha256':sha256(ROOT/'reports/q1_3_rule_probe.json'),
                    'real_data_risk':'候选视图保留极值正单；条件性移除会改变金额、发票数和最近购买',
                    'synthetic_example_scope':'仅示例的算术与已声明假设，不是部分退货算法测试',
                    'matching_approval':'未确认，不把同客同品同价自动当成唯一原单'}
        e.check('真实个案由独立读取核验；净额守恒的反例',counterexample)
        def regression():
            cli([ROOT/'scripts/verify_q1_review.py'],timeout=480)
            report=json.loads((ROOT/'reports/q1_2/review_validation_latest.json').read_text())
            assert report['status']=='passed' and report['source_sha256']==e.report['source_sha256']
            cli([ROOT/'run_all.py','--stage','q1','--offline','--q1-output-dir',temp/'all-q1','--report',temp/'q1.json'])
            stages=json.loads((temp/'q1.json').read_text())['results']
            assert [(s['stage'],s['status']) for s in stages]==[('q1.1','passed'),('q1.2','passed'),('q1.3','passed')]
            return {'q1_review_run':report['run_id'],'q1_stage':'三个题目交付入口通过；不认证业务规则或宣称 Q2–Q5 完成'}
        e.check('当前代码回归与 Q1 三阶段接线',regression)
        e.report['semantic_review']={'reviewer':'同一 Codex；非独立业务人员',
          'document':'q1_data_quality/strategy_review.md','business_approval':'未获得',
          'scope':'用途策略和反例讨论；没有自动证明自然语言解释正确'}
        e.save()
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
