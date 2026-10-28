"""Q1.2 验收：独立全量复算、反例、错误植入、入口一致和历史回归。"""

from datetime import datetime
from decimal import Decimal
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from q1_findings_reference import compare, reference
from experiment_q1_2_sensitivity import experiment
from verify_q1_1 import test_suite
from verification_support import EvidenceRun, ROOT, sha256

MUTATIONS = [
    ('错误取绝对金额', "f['_amount'] = f['_p'] * f['_q']", "f['_amount'] = (f['_p'] * f['_q']).abs()"),
    ('价格先舍入到分', 'scale = 10 ** precision', 'precision = 2\n    scale = 10 ** precision'),
    ('把明细行数当订单数', 'invoices = int(g.Invoice.nunique())', 'invoices = len(g)'),
    ('编码静默去空格', "f.StockCode.str.fullmatch(r'[0-9]+[A-Za-z]*')", "f.StockCode.str.strip().str.fullmatch(r'[0-9]+[A-Za-z]*')"),
    ('商品频次误按明细行数', "products.sort(key=lambda x: (-x['invoices'], x['code']))", "products.sort(key=lambda x: (-x['rows'], x['code']))"),
]


def main():
    with EvidenceRun(ROOT/'reports/q1_2','acceptance') as e, tempfile.TemporaryDirectory(prefix='gekko-q12-') as directory:
        temp = Path(directory)
        original = ROOT/'data/online_retail_ii.csv'
        before = sha256(original)
        def units():
            result = test_suite(ROOT, 'test*.py')
            assert result['tests'] >= 38 and not result['failures'] and not result['errors'], str(result)
            return result
        if not e.check('Q12-1 手算反例、置换不变性、成对冲销及回归',units):
            return 1
        for name, old, new in MUTATIONS:
            def mutant():
                with tempfile.TemporaryDirectory(prefix='gekko-q12-mutant-') as folder:
                    project=Path(folder)
                    for rel in ['download_data.py','q1_data_quality/q1_findings.py','scripts/q1_findings_reference.py','tests/test_q1_findings.py']:
                        path=project/rel; path.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copyfile(ROOT/rel,path)
                    path=project/'q1_data_quality/q1_findings.py'
                    source=path.read_text()
                    assert source.count(old)==1, '变异位置不唯一'
                    path.write_text(source.replace(old,new),encoding='utf-8')
                    result=test_suite(project,'test_q1_findings.py')
                    assert result['failures'] and not result['errors'], f'未以纯断言失败抓错：{result}'
                    return result
            e.check(f'Q12-3 故意植错：{name}',mutant)
        direct,integrated=temp/'direct',temp/'integrated'
        def cli(args, timeout=240):
            r=subprocess.run([sys.executable,*args],cwd=temp,capture_output=True,text=True,timeout=timeout)
            assert r.returncode==0, f'进程未通过，退出码 {r.returncode}，末尾输出：{r.stdout[-1200:]}'
        def entrypoints():
            cli([str(ROOT/'q1_data_quality/q1_findings.py'),'--output-dir',str(direct)])
            cli([str(ROOT/'run_all.py'),'--stage','q1.2','--q1-output-dir',str(integrated),'--report',str(temp/'run.json')])
            report=json.loads((temp/'run.json').read_text())
            assert [(r['stage'],r['status']) for r in report['results']]==[('q1.2','passed')]
            hashes={}
            for name in ['findings.md','findings_metrics.json']:
                assert (direct/name).read_bytes()==(integrated/name).read_bytes()==(ROOT/'q1_data_quality'/name).read_bytes(), name
                hashes[name]=sha256(direct/name)
            return {'artifacts':hashes,'independent_stage':'q1.2'}
        if not e.check('Q12-4 独立入口/总入口/交付产物逐字节相同',entrypoints):
            return 1
        actual=json.loads((direct/'findings_metrics.json').read_text())
        def independent():
            expected=reference(original)
            compare(expected,{k:v for k,v in actual.items() if k!='source'})
            assert actual['source']['sha256']==before
            assert sum(v['rows'] for v in actual['prefixes'].values())==actual['rows']
            assert sum(Decimal(v['net']) for v in actual['prefixes'].values())==Decimal(actual['total']['net'])
            assert sum(v['rows'] for v in actual['special_codes'].values())==actual['special_total']['rows']
            assert sum(Decimal(v['net']) for v in actual['special_codes'].values())==Decimal(actual['special_total']['net'])
            assert sum(v['rows'] for v in actual['customers'].values())==actual['rows']
            assert sum(Decimal(v['net']) for v in actual['customers'].values())==Decimal(actual['total']['net'])
            return {'method':'CSV + Decimal + Counter + set，无生产业务导入', 'compared':'JSON 全部业务字段，包括分组、排序、记录及份额',
                    'tolerance':'整数/金额/文本精确相同，比率和均额绝对误差 <= 1e-12',
                    'rows':expected['rows'],'total_net':expected['total']['net'], 'special_codes':len(expected['special_codes']),
                    'reference_digest':__import__('hashlib').sha256(json.dumps(expected,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
        e.check('Q12-2 全量独立复算与分组守恒',independent)
        def narrative():
            # 另行检查报告中的业务解释前提，不以文案存在当作业务结论成立。
            rows=actual['extremes']; assert len(rows)==2
            a,b=sorted(rows,key=lambda r:r['InvoiceDate'])
            for key in ['Customer ID','StockCode','Price']:
                assert a[key]==b[key]
            assert Decimal(a['Quantity'])==-Decimal(b['Quantity'])==80995
            assert (datetime.fromisoformat(b['InvoiceDate'])-datetime.fromisoformat(a['InvoiceDate'])).total_seconds()==720
            assert Decimal(a['Price'])*Decimal(a['Quantity'])==Decimal('168469.600')
            negatives=actual['negative_prices']; assert len(negatives)==5
            for r in negatives:
                assert r['Invoice'].startswith('A') and r['StockCode']=='B' and r['Quantity']=='1'
                assert r['Customer ID']=='' and r['Country']=='United Kingdom' and r['Description']=='Adjust bad debt'
            assert actual['prefixes']['A']['price_sign']=={'negative':5,'zero':0,'positive':1}
            missing,present=actual['customers']['missing'],actual['customers']['present']
            assert missing['invoice_mean']<present['invoice_mean']
            assert missing['candidate_sales']['invoice_mean']>present['candidate_sales']['invoice_mean']
            assert missing['candidate_sales']['rows']/missing['candidate_sales']['invoices'] > present['candidate_sales']['rows']/present['candidate_sales']['invoices']
            assert missing['countries']['United Kingdom']['within_group_share']>present['countries']['United Kingdom']['within_group_share']
            report=(direct/'findings.md').read_text()
            for heading in ['## 1.','## 2.','## 3.','## 4.']:
                assert heading in report
            for code in actual['special_codes']:
                assert '| '+json.dumps(code,ensure_ascii=False).replace('|','\\|')+' |' in report
            for r in rows+negatives:
                assert f"| {r['record']} |" in report
            assert '不能证明' in report and '业务含义未知' in report and '排序反转' in report
            return {'extreme_pair':'同客户、商品、价格，12 分钟后冲销；原因未知', 'negative_price_rows':5,
                    'customer_average_reverses':True,'all_code_rows_present':len(actual['special_codes']),
                    'limitation':'这是数据解释前提核验，不是业务人员审核，也不证明缺失身份成因'}
        e.check('Q12-5 报告关键解释前提与完整覆盖',narrative)
        def sensitivity():
            fixture=temp/'sensitivity_fixture.csv'
            with fixture.open('w',newline='') as stream:
                writer=csv.writer(stream)
                writer.writerow(['Invoice','StockCode','Quantity','Price','Customer ID'])
                writer.writerows([['1','001','2','1','a'],['1','001','1','-1',''],['C2','001','-1','2','a'],['3','POST','1','3','']])
            observed=experiment(fixture)
            # 预期值独立手算；依次为缺失/非缺失的行数、不同发票数和精确金额。
            expected={'raw':[(2,2,'2'),(2,2,'0')], 'positive_quantity_only':[(2,2,'2'),(1,1,'2')],
                      'positive_price_only':[(1,1,'3'),(2,2,'0')], 'numeric_invoice_only':[(2,2,'2'),(1,1,'2')],
                      'ordinary_code_only':[(1,1,'-1'),(2,2,'0')], 'positive_quantity_and_price':[(1,1,'3'),(1,1,'2')],
                      'positive_and_numeric_invoice':[(1,1,'3'),(1,1,'2')], 'candidate':[(0,0,'0'),(1,1,'2')]}
            for view,pairs in expected.items():
                for group,(rows,invoices,net) in zip(['missing','present'],pairs):
                    v=observed[view][group]
                    assert (v['rows'],v['invoices'],Decimal(v['net']))==(rows,invoices,Decimal(net)), (view,group)
                    assert v['invoice_mean']==(str(Decimal(net)/invoices) if invoices else None)
            cli([str(ROOT/'scripts/experiment_q1_2_sensitivity.py')])
            report=json.loads((ROOT/'reports/q1_2/sensitivity_latest.json').read_text())
            assert report['status']=='passed' and report['source_sha256']==e.report['source_sha256']
            views=report['checks'][0]['evidence']['views']
            for view in ['raw','candidate']:
                for group in ['missing','present']:
                    v=views[view][group]
                    base=actual['customers'][group] if view=='raw' else actual['customers'][group]['candidate_sales']
                    assert v['rows']==base['rows'] and v['invoices']==base['invoices'] and Decimal(v['net'])==Decimal(base['net'])
            for view in ['positive_quantity_only','positive_price_only']:
                assert Decimal(views[view]['missing']['invoice_mean'])>Decimal(views[view]['present']['invoice_mean'])
            for view in ['raw','numeric_invoice_only','ordinary_code_only']:
                assert Decimal(views[view]['missing']['invoice_mean'])<Decimal(views[view]['present']['invoice_mean'])
            return {'run_id':report['run_id'],'hand_checked_views':8,'report_sha256':sha256(ROOT/'reports/q1_2_sensitivity.md'),
                    'conclusion':'单独数量或单价过滤已使排序反转，不能唯一归因于特殊编码排除'}
        e.check('Q12-新增实验 单条件消融手算、全量运行及首尾交叉核对',sensitivity)
        def regression():
            cli([str(ROOT/'scripts/verify_q1_1.py')],timeout=300)
            old=json.loads((ROOT/'reports/q1_1/acceptance_latest.json').read_text())
            assert old['status']=='passed' and old['source_sha256']==e.report['source_sha256']
            assert before==sha256(original)
            return {'q1_1_current_regression':old['run_id'],'includes':'原有骨架六个真实流程和旧五类变异；源文件/README/.gitignore 不变；依赖安装证明复用范围见 Q1.1 报告'}
        e.check('Q12-4/6 当前源码的 Q1.1、骨架和旧变异回归',regression)
    print(e.path)
    print('Q1.2 规定计算检查通过；业务放行仍须补证，见 reports/q1_2_review.md' if e.report['status']=='passed' else 'Q1.2 计算检查未通过，禁止据此放行')
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
