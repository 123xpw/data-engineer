"""Q2.3 手算、指定错误、全部卖家独立复算及正式入口验收。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verification_support import EvidenceRun,require,atomic_json
from scripts.check_q2_3_cases import check_cases
from scripts.q2_3_reference import read_reference
from q2_sql_analysis.q2_3 import query,execute,SQL
from q2_sql_analysis.mysql_runtime import ensure_mysql,connect
from artifact_manifest import validate_manifest,manifest_path


def command(args,expected=0,timeout=900):
    result=subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=timeout)
    require(result.returncode==expected,f'进程退出 {result.returncode}，预期 {expected}：{result.stdout[-1800:]} {result.stderr[-800:]}')


def main():
    with EvidenceRun(ROOT/'reports/q2_3','acceptance') as e:
        if not e.check('真实 MySQL 环境',ensure_mysql):return 1
        if not e.check('手算、连接粒度、分母、并列、截断及定向错误',check_cases):return 1
        def real_data():
            ref=read_reference();actual=query()
            require(actual['sellers']==ref['top20'],'TOP20 逐字段与原始 CSV 独立复算不同')
            with connect() as c:
                all_rows=execute(c,SQL.read_text().replace(' LIMIT 20',''))
            require(all_rows==ref['all_sellers'],'全部卖家逐字段不一致')
            require(actual['unattributed_orders']==ref['unattributed_orders'] and actual['unattributed_canceled_orders']==ref['unattributed_canceled_orders'],'未归属分母不一致')
            atomic_json(ROOT/'reports/q2_3_reference.json',ref)
            return {'sellers':len(all_rows),'orders_2017':ref['orders_2017'],'attributed_orders':ref['attributed_orders'],
                'unattributed_orders':ref['unattributed_orders'],'unattributed_canceled_orders':ref['unattributed_canceled_orders'],
                'gmv':ref['delivered_gmv'],'review_rule_sensitive_sellers':len(ref['review_sensitivity']),
                'sensitivity_examples':ref['review_sensitivity'][:3],'top_seller':actual['sellers'][0]}
        if not e.check('全部真实卖家独立复算、金额及评价规则敏感性',real_data):return 1
        def entries():
            with tempfile.TemporaryDirectory(prefix='gekko-q23-') as folder:
                root=Path(folder);out=root/'out';report=root/'run.json'
                command([ROOT/'run_all.py','--stage','q2.3','--q2-output-dir',out,'--report',report])
                top=json.loads(report.read_text());validate_manifest(manifest_path(out,'q2.3'),top['run_id'])
                combined=json.loads((out/'q2_3_results.json').read_text())
                command([ROOT/'q2_sql_analysis/q2_3.py','--skip-load','--output-dir',root/'direct'])
                direct=json.loads((root/'direct/q2_3_results.json').read_text());require(combined==direct,'独立入口与总入口不同')
                command([ROOT/'run_all.py','--stage','q2.3','--data-dir',root/'missing','--q2-output-dir',out,'--report',report],1)
                failed=json.loads(report.read_text());require(json.loads(manifest_path(out,'q2.3').read_text())['status']=='blocked_dependency','依赖失败未登记')
                try:validate_manifest(manifest_path(out,'q2.3'),failed['run_id'])
                except ValueError:pass
                else:raise AssertionError('失败后旧产物仍被接受')
            return {'direct_combined_equal':True,'failed_old_artifact_rejected':True}
        if not e.check('本题正式入口与失败归属',entries):return 1
        def regression():
            command([ROOT/'scripts/verify_q2_2.py'],timeout=1800)
            old=json.loads((ROOT/'reports/q2_2/acceptance_latest.json').read_text())
            require(old['status']=='passed' and old['source_sha256']==e.report['source_sha256'],'旧业务回归不是当前源码')
            query()
            return {'run_id':old['run_id'],'scope':'包含 Q1、九表、Q2.1、Q2.2 当前源码回归'}
        e.check('已有业务当前源码回归',regression)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
