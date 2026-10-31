"""Q2.4 正式验收：冻结 SQL、实测证据、独立复算与当前全入口。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import publish,source_hashes,validate_manifest,manifest_path
from scripts.verification_support import EvidenceRun,require,sha256
from scripts.q2_4_reference import read_reference
from audit.q2_4_experiment import ORIGINAL,EQUIVALENT,CORRECTED,hand_probe
from q2_sql_analysis.q2_4 import query
from q2_sql_analysis.mysql_runtime import ensure_mysql


def main():
    with EvidenceRun(ROOT/'reports/q2_4','acceptance') as e:
        if not e.check('真实 MySQL 与 TLS 就绪',ensure_mysql):return 1
        def frozen_experiment():
            proof=json.loads((ROOT/'reports/q2_4/experiment_latest.json').read_text())
            require(proof['status']=='passed','没有真实计时实验通过证据')
            require(proof['experiment_sha256']==sha256(ROOT/'audit/q2_4_experiment.py'),'计时 SQL 原型改变，必须重测')
            require(proof['verifier_sha256']==sha256(ROOT/'audit/verify_q2_4_experiment.py'),'计时协议改变，必须重测')
            for name in ['requirements.txt','data_sources.json']:
                require(proof['source_sha256'][name]==sha256(ROOT/name),'数据或依赖变化，计时证据过期')
            for name,sql in [('original',ORIGINAL),('equivalent',EQUIVALENT),('corrected',CORRECTED)]:
                require((ROOT/f'q2_sql_analysis/q2_4_{name}.sql').read_text().strip().rstrip(';')==sql,'正式 SQL 与实测版本不一致')
            return {'run_id':proof['run_id'],'hand':hand_probe(),'scope':'原型 SQL、依赖与数据均未变化；正式入口另验'}
        if not e.check('冻结 SQL、真实计时证据与手算反例',frozen_experiment):return 1
        def regression():
            r=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q2_3.py')],cwd=ROOT,capture_output=True,text=True,timeout=2400)
            require(r.returncode==0,r.stdout[-2000:]+r.stderr[-500:])
            prior=json.loads((ROOT/'reports/q2_3/acceptance_latest.json').read_text())
            require(prior['status']=='passed' and prior['source_sha256']==e.report['source_sha256'],'回归证据不是当前源码')
            return {'run_id':prior['run_id'],'includes':'Q1、九表、Q2.1–Q2.3 与默认全入口实际执行 Q2.4'}
        if not e.check('当前源码既有业务回归及默认四题入口',regression):return 1
        def actual():
            result=publish('q2.4',ROOT/'q2_sql_analysis',query)
            ref=read_reference();require(result['states']==ref['corrected'],'正式修正版不符独立原始 CSV 复算')
            top=json.loads((ROOT/'reports/release_execution.json').read_text());folder=Path(top['output_directories']['q2'])
            validate_manifest(manifest_path(folder,'q2.4'),top['run_id'])
            candidate=json.loads((folder/'q2_4_results.json').read_text())
            require(candidate==result,'默认全入口与独立计算结果不同')
            with tempfile.TemporaryDirectory(prefix='gekko-q24-cli-') as folder_name:
                folder=Path(folder_name)
                args=[sys.executable,str(ROOT/'q2_sql_analysis/q2_4.py'),'--output-dir',str(folder)]
                direct=subprocess.run(args+['--skip-load'],cwd=folder,capture_output=True,text=True,timeout=180)
                require(direct.returncode==0,'独立 CLI 失败')
                require(json.loads((folder/'q2_4_results.json').read_text())==result,'独立 CLI 数值不一致')
                failed=subprocess.run(args+['--data-dir',str(folder/'missing')],cwd=folder,capture_output=True,text=True,timeout=60)
                require(failed.returncode==1,'缺输入未失败')
                manifest=json.loads(manifest_path(folder,'q2.4').read_text())
                require(manifest['status']=='failed','失败清单未替换旧成功')
                try:validate_manifest(manifest_path(folder,'q2.4'),manifest['run_id'])
                except ValueError:pass
                else:raise AssertionError('失败旧产物仍被接受')

            return {'states':len(result['states']),'target_orders':ref['target_orders'],'SP':result['states'][0],
                'pipeline_run_id':top['run_id'],'limits':'原查询语义的性能候选未证明提速；修正均值是业务选择而非权威性认证'}
        if not e.check('本题正式发布、逐州独立复算与全入口归属',actual):return 1
        e.report.update(requirement_id='Q2.4',production_source_sha256=source_hashes(),review_scope='Q2.4 冻结 SQL、真实计时、独立复算、正式发布和默认全入口；无百倍性能结论')
        e.report['artifact_sha256']={str(p.relative_to(ROOT)):sha256(p) for p in [ROOT/'q2_sql_analysis/q2_4_results.json',ROOT/'q2_sql_analysis/q2_4_query_optimization.md',ROOT/'reports/q2_4_experiment.json']}
        e.save()
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
