"""实测当前门槛：局部可扩展与完整不可交付必须同时如实成立。"""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verification_support import EvidenceRun,require,sha256


def invoke(arguments,expected,timeout=120):
    result=subprocess.run([sys.executable,*arguments],cwd=ROOT,timeout=timeout,capture_output=True,text=True)
    require(result.returncode==expected,f'预期 {expected}，实际 {result.returncode}：{result.stdout[-2200:]} {result.stderr[-600:]}')
    return {'exit_code':result.returncode}


def main():
    with EvidenceRun(ROOT/'reports/repairs/r4','acceptance') as e:
        e.report['repair_contract_sha256']=sha256(ROOT/'repairs/R4_ACCEPTANCE.md')
        e.report['repair_script_sha256']=sha256(Path(__file__))
        e.check('缺项、过期、伪声明、篡改与优化模式反证',lambda:invoke(['-m','unittest','discover','-s','tests','-q'],0))
        if not e.check('当前源码完整回归与全入口重跑',lambda:invoke(['release_check.py','--scope','implemented','--refresh'],0,2400)):
            return 1
        def partial_not_complete():
            invoke(['release_check.py'],2)
            report=json.loads((ROOT/'reports/release/submission_latest.json').read_text())
            require(report['implemented_ready'] is True and report['decision']=='not_ready','局部与全项目结论混淆')
            require(bool(report['pending_requirements']),'没有披露缺项')
            return {'implemented_ready':True,'submission_ready':False,'missing':[r['id'] for r in report['pending_requirements']],
                    'submission_run_id':report['run_id']}
        e.check('全部已实现检查通过仍不能掩盖必答缺项',partial_not_complete)
        e.check('旧历史入口转发到同一当前判定',lambda:invoke(['scripts/verify_stage_gate.py'],2))
        def optimization():
            invoke(['-O','release_check.py','--scope','implemented'],1)
            report=json.loads((ROOT/'reports/release/implemented_latest.json').read_text())
            require(report['status']=='failed' and report['python_optimization_level']==1,'优化模式未明确拒绝')
            invoke(['release_check.py','--scope','implemented'],0)
            return {'optimized_rejected':True,'normal_mode_rechecked':True}
        e.check('新放行器同样拒绝优化模式并恢复正常检查',optimization)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
