"""真实 CLI 成功后故障重放，并重跑独立业务复算链。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import digest, manifest_path, validate_manifest
from scripts.verification_support import EvidenceRun, require, sha256
from scripts.q2_2_reference import read_reference


def run(args, expected, timeout=120):
    result=subprocess.run([sys.executable,*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=timeout)
    require(result.returncode==expected,f'子进程退出码 {result.returncode}，预期 {expected}：{result.stdout[-1200:]} {result.stderr[-1200:]}')
    return result


def main():
    with EvidenceRun(ROOT/'reports/repairs/r3','acceptance') as e:
        e.report['repair_contract_sha256']=sha256(ROOT/'repairs/R3_ACCEPTANCE.md')
        e.report['repair_script_sha256']=sha256(Path(__file__))
        e.check('消费端协议、漏写、篡改、编号、中断与独立题隔离',lambda: {'exit_code':run(['-m','unittest','discover','-s','tests','-q'],0).returncode})
        def real_failure():
            with tempfile.TemporaryDirectory(prefix='gekko-r3-') as folder:
                output=Path(folder)/'output';report=Path(folder)/'run.json'
                run([ROOT/'q2_sql_analysis/q2_2.py','--skip-load','--output-dir',output],0)
                path=manifest_path(output,'q2.2')
                first=json.loads(path.read_text());validate_manifest(path,first['run_id'])
                actual=json.loads((output/'q2_2_results.json').read_text())
                require(actual['months']==read_reference()['months'],'真实结果与独立复算不同')
                old=digest(output/'q2_2_results.json')
                run([ROOT/'run_all.py','--stage','q2.2','--data-dir',Path(folder)/'missing','--q2-output-dir',output,'--report',report],1)
                second=json.loads(path.read_text());top=json.loads(report.read_text())
                require(second['run_id']==top['run_id'] and second['run_id']!=first['run_id'],'运行编号未关联')
                require(second['status']=='blocked_dependency' and second['artifacts']=={},'失败错误发布了产物')
                require(old==digest(output/'q2_2_results.json'),'缺输入改变了旧业务文件')
                run([ROOT/'artifact_manifest.py','--manifest',path,'--run-id',second['run_id']],1)
                run([ROOT/'artifact_manifest.py','--manifest',path,'--run-id',first['run_id']],1)
                run([ROOT/'q2_sql_analysis/q2_2.py','--data-dir',Path(folder)/'missing','--output-dir',output],1)
                direct=json.loads(path.read_text());require(direct['status']=='failed','独立 CLI 未登记失败')
                require(old==digest(output/'q2_2_results.json'),'独立失败改变了旧业务文件')
                return {'success_run':first['run_id'],'blocked_run':second['run_id'],
                        'direct_failed_run':direct['run_id'],'old_bytes_preserved':True,
                        'both_old_and_new_run_rejected_after_failure':True,'independent_months':len(actual['months'])}
        e.check('真实月度 CLI 成功→缺输入故障→消费端拒绝',real_failure)
        def regression():
            run([ROOT/'scripts/verify_q2_2.py'],0,1800)
            report=json.loads((ROOT/'reports/q2_2/acceptance_latest.json').read_text())
            require(report['status']=='passed' and report['source_sha256']==e.report['source_sha256'],'回归证据不是当前源码')
            return {'run_id':report['run_id'],'scope':'Q2.2→Q2.1→Q1 完整已实现范围；不含未完成题目'}
        e.check('当前源码已有业务独立复算全链路',regression)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
