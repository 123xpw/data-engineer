"""Q2.2 独立逐月复算、错误口径实测、入口隔离与已有模块回归。"""

from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from q2_sql_analysis.mysql_runtime import ensure_mysql,connect
from q2_sql_analysis.q2_2 import query
from scripts.check_q2_2_cases import check_cases
from scripts.q2_2_reference import read_reference
from scripts.verification_support import EvidenceRun,sha256,atomic_json


def main():
    with EvidenceRun(ROOT/'reports/q2_2','acceptance') as e:
        if not e.check('真实 MySQL 与本地项目环境',ensure_mysql):
            return 1
        if not e.check('独立参考校准、手算、变换、错误注入与边界',check_cases):
            return 1
        def real_data():
            expected=read_reference();actual=query()
            assert actual['months']==expected['months'],'真实逐月数值或诊断分母不一致'
            atomic_json(ROOT/'reports/q2_2_reference.json',expected)
            return {'months':len(actual['months']),'orders':sum(r['total_orders'] for r in actual['months']),
                    'delivered':sum(r['delivered_orders'] for r in actual['months']),
                    'canceled':sum(r['canceled_orders'] for r in actual['months']),
                    'gmv':str(sum(Decimal(r['delivered_gmv']) for r in actual['months'])),
                    'missing_time':sum(r['missing_delivery_time_orders'] for r in actual['months']),
                    'reference':'原始 CSV/订单字典/Decimal/datetime；逐月全部列比较，不调用生产聚合函数'}
        if not e.check('真实全部月份及诊断列独立复算',real_data):
            return 1
        def wrong_queries():
            reference=read_reference()['diagnostics']['wrong_join_experiment']
            observed={}
            with connect() as c,c.cursor() as cur:
                for name,join in [('left','LEFT JOIN'),('inner','INNER JOIN')]:
                    cur.execute(f"SELECT COUNT(*), SUM(o.order_status='canceled'), ROUND(CAST(SUM(CASE WHEN o.order_status='delivered' THEN TIMESTAMPDIFF(SECOND,o.order_purchase_timestamp,o.order_delivered_customer_date) END) AS DECIMAL(30,12))/NULLIF(SUM(o.order_status='delivered' AND o.order_purchase_timestamp IS NOT NULL AND o.order_delivered_customer_date IS NOT NULL)*86400,0),6) FROM orders o {join} order_items i ON o.order_id=i.order_id")
                    rows,canceled,days=cur.fetchone()
                    assert rows==reference[f'{name}_detail_rows']
                    assert int(canceled)==reference[f'{name}_join_canceled_rows']
                    assert str(days)==reference['detail_weighted_avg_days']
                    observed[name]={'joined_rows':rows,'canceled_rows':int(canceled),'weighted_avg_days':str(days)}
            assert observed['left']['joined_rows']!=reference['correct_orders']
            assert observed['left']['weighted_avg_days']!=reference['correct_avg_days']
            return {'wrong_sql_observed':observed,'independent_reference':reference,
                    'limitation':'错误查询只作实验，未替换正式输出；敏感性不证明哪种业务定义是唯一正确'}
        e.check('真实数据直接连接的偏差与独立敏感性',wrong_queries)
        def isolation():
            from run_all import q2_scope
            def fake_load(data_dir, report):
                report.parent.mkdir(parents=True,exist_ok=True)
                report.write_text('{"test_only": true}')
                return {'test_only': True}
            def fake_monthly(output):
                (output/'q2_2_results.json').write_text('{"test_only": true}')
                (output/'q2_2_findings.md').write_text('人工控制流夹具，不是业务证据')
                return {'test_only': True}
            with tempfile.TemporaryDirectory() as folder, \
                 patch('q2_sql_analysis.load_olist.load',side_effect=fake_load), \
                 patch('q2_sql_analysis.q2_1.query',side_effect=RuntimeError('人工故障')), \
                 patch('q2_sql_analysis.q2_2.query',side_effect=fake_monthly) as monthly:
                report=q2_scope(ROOT/'data',Path(folder))
                assert report['stage_completion']=='failed'
                assert [(r['stage'],r['status']) for r in report['results']]==[('q2.load','passed'),('q2.1','failed'),('q2.2','passed')]
                monthly.assert_called_once()
            return {'q21_failure_does_not_block_independent_q22':True,'mock_scope':'仅验证控制流；SQL 另有真实 MySQL 实验'}
        e.check('同模块独立题目失败隔离',isolation)
        def entrypoints():
            with tempfile.TemporaryDirectory(prefix='gekko-q22-') as folder:
                tmp=Path(folder)
                cmd=[sys.executable,str(ROOT/'run_all.py'),'--stage','q2.2','--q2-output-dir',str(tmp/'entry'),'--report',str(tmp/'run.json')]
                r=subprocess.run(cmd,cwd=tmp,capture_output=True,text=True,timeout=360)
                assert r.returncode==0,f'Q2.2 总入口失败 {r.returncode}'
                report=json.loads((tmp/'run.json').read_text());assert report['results'][0]['status']=='passed'
                direct=subprocess.run([sys.executable,str(ROOT/'q2_sql_analysis/q2_2.py'),'--skip-load','--output-dir',str(tmp/'direct')],cwd=tmp,capture_output=True,text=True,timeout=120)
                assert direct.returncode==0
                results=[json.loads((d/'q2_2_results.json').read_text()) for d in (tmp/'entry',tmp/'direct',ROOT/'q2_sql_analysis')]
                for result in results[1:]:
                    assert {k:v for k,v in result.items() if k!='load_version'}=={k:v for k,v in results[0].items() if k!='load_version'}
                missing=subprocess.run(cmd+['--data-dir',str(tmp/'missing')],cwd=tmp,capture_output=True,text=True,timeout=60)
                assert missing.returncode==1
                stages=json.loads((tmp/'run.json').read_text())['results'][0]['detail']['results']
                assert [(r['stage'],r['status']) for r in stages]==[('q2.load','failed'),('q2.2','blocked_dependency')]
            return {'outside_cwd':True,'direct_and_combined_business_results_equal':True,'missing_input_blocks_query':True}
        e.check('独立/总入口与真实缺输入故障',entrypoints)
        def regression():
            r=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q2_1.py')],cwd=ROOT,capture_output=True,text=True,timeout=900)
            assert r.returncode==0,r.stdout[-1600:]
            previous=json.loads((ROOT/'reports/q2_1/acceptance_latest.json').read_text())
            assert previous['status']=='passed' and previous['source_sha256']==e.report['source_sha256']
            # 回归会重载批次，最后再核对一次当前批次并更新正式 Q2.2 产物。
            current=query();expected=read_reference();assert current['months']==expected['months']
            return {'q21_full_run':previous['run_id'],'includes_q1_regression':True,
                    'fresh_environment':'无新依赖，复用锁定依赖安装证明；本轮新代码在当前环境执行'}
        e.check('九表/Q2.1/Q1 当前源码回归与最终批次复算',regression)
        e.report['artifact_sha256']={p:sha256(ROOT/p) for p in ['q2_sql_analysis/q2_2_results.json','q2_sql_analysis/q2_2_findings.md','reports/q2_2_reference.json']}
        e.report['scope']='仅 Q2.2 明示口径；不声明全项目、并发恢复或业务认证完成'
        e.save()
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
