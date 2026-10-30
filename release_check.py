"""当前唯一交付判定：局部范围可扩展，与完整项目可提交分开。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from artifact_manifest import ARTIFACTS, digest, manifest_path, source_hashes, validate_manifest
from scripts.verification_support import EvidenceRun, require

REQUIRED_PENDING={'Q2.3','Q2.4','Q3.1','Q4.1','Q5.1','DOCS','AI_LOG','COLD_START','PUBLIC_FORK','FINAL_COMMIT','HUMAN_REVIEW'}
REGRESSION_CHECKS={
    '真实 MySQL 与本地项目环境', '独立参考校准、手算、变换、错误注入与边界',
    '真实全部月份及诊断列独立复算', '真实数据直接连接的偏差与独立敏感性',
    '同模块独立题目失败隔离', '独立/总入口与真实缺输入故障',
    '九表/Q2.1/Q1 当前源码回归与最终批次复算',
}
PIPELINE=ROOT/'reports/release_execution.json'
REGRESSION=ROOT/'reports/q2_2/acceptance_latest.json'


def read(path):
    return json.loads(Path(path).read_text())


def inspect_regression(report, current):
    require(report.get('status')=='passed','当前功能回归未通过')
    checks=report.get('checks',[])
    require({c['name'] for c in checks}==REGRESSION_CHECKS and len(checks)==len(REGRESSION_CHECKS), '关键检查缺失、重复或范围变化；需审查验收契约')
    require(all(c.get('passed') is True for c in checks),'存在失败检查')
    require(report.get('source_sha256')==current,'功能回归源码已过期')
    for path,value in report.get('artifact_sha256',{}).items():
        require(digest(ROOT/path)==value,f'回归产物已变化：{path}')
    require(bool(report.get('artifact_sha256')),'缺少回归产物指纹')
    return {'run_id':report['run_id'],'report_sha256':digest(REGRESSION),'scope':'当前源码的 Q1、九表、Q2.1、Q2.2；不含未完成题'}


def inspect_dependencies():
    path=ROOT/'reports/hardening/clean_environment_latest.json';report=read(path)
    require(report.get('status')=='passed','依赖安装证明未通过')
    require(report.get('source_sha256',{}).get('requirements.txt')==digest(ROOT/'requirements.txt'),'依赖锁变化，必须重新安装验证')
    install=next((c for c in report.get('checks',[]) if c['name']=='锁定依赖从零安装且版本一致'),None)
    require(install is not None and install.get('passed') is True,'缺少实际从零安装记录')
    return {'run_id':report['run_id'],'report_sha256':digest(path),'scope':'仅复用相同 requirements 的安装证明；当前源码另跑功能回归',
            'environment':{'python':report['python'],'platform':report['platform']}}


def inspect_execution():
    report=read(PIPELINE)
    require(report.get('requested_stage')=='all','需要真实全入口执行记录')
    require(report.get('source_sha256')==source_hashes(),'全入口运行源码已变化')
    rows={r['stage']:r for r in report['results']}
    for stage in ('data.retail','data.olist','q1.1','q1.2','q1.3'):
        require(rows.get(stage,{}).get('status')=='passed',f'{stage} 未成功')
    require(rows.get('q2',{}).get('status') in ('passed','partial'),'Q2 已实现部分运行失败')
    nested={r['stage']:r for r in rows['q2']['detail']['results']}
    for stage in ('q2.load','q2.1','q2.2'):
        require(nested.get(stage,{}).get('status')=='passed',f'{stage} 未成功')
    outputs=report['output_directories']; validated={}
    for stage in ARTIFACTS:
        folder=Path(outputs['q1' if stage.startswith('q1') else 'q2'])
        record=validate_manifest(manifest_path(folder,stage),report['run_id'])
        validated[stage]={'manifest_sha256':digest(manifest_path(folder,stage)),'artifacts':record['artifacts']}
    # 再执行产生新的数据库批次；只豁免随机批次号，所有业务字段必须相等。
    for group,name in [('q1','data_quality_metrics.json'),('q1','findings_metrics.json'),
                       ('q2','q2_1_results.json'),('q2','q2_2_results.json')]:
        original=read(ROOT/('q1_data_quality' if group=='q1' else 'q2_sql_analysis')/name)
        actual=read(Path(outputs[group])/name)
        require({k:v for k,v in actual.items() if k!='load_version'}=={k:v for k,v in original.items() if k!='load_version'},f'独立回归结果与本轮正式 CLI 不一致：{name}')
    return {'run_id':report['run_id'],'exit_code':report['exit_code'],'report_sha256':digest(PIPELINE),'manifests':validated,
            'scope':'当前环境、已下载冻结输入；不是完整冷启动证明'}


def inspect_runtime_repair():
    path=ROOT/'reports/repairs/r2/acceptance_latest.json'
    report=read(path)
    require(report.get('status')=='passed','数据库生命周期修复没有通过证据')
    key='q2_sql_analysis/mysql_runtime.py'
    require(report.get('source_sha256',{}).get(key)==digest(ROOT/key),'数据库配置逻辑变化，需重跑生命周期实验')
    require(report.get('repair_script_sha256')==digest(ROOT/'repairs/verify_r2.py'),'生命周期验收脚本已变化')
    return {'run_id':report['run_id'],'scope':'仅复用未变 mysql_runtime 的本机生命周期实验；当前连接与业务仍另跑'}


def inspect_protected():
    base='648b3c50a0792c691ead296dd834bda330a0c2e7'
    for name in ('README.md','.gitignore','data_sources.json'):
        original=subprocess.check_output(['git','show',f'{base}:{name}'],cwd=ROOT)
        require((ROOT/name).read_bytes()==original,f'受保护文件改变：{name}')
    tracked=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
    bad=[p for p in tracked if p.endswith(('.csv','.parquet','.xlsx','.zip','.pem','.key')) or Path(p).name in ('.env','credentials.json')]
    require(not bad,'Git 中存在数据集或私有配置文件')
    return {'protected_unchanged':True,'datasets_and_private_config_not_tracked':True}


def pending_items(items):
    require({r['id'] for r in items}==REQUIRED_PENDING and len(items)==len(REQUIRED_PENDING),'提交清单缺项、重复或范围改变')
    pending=[]
    for row in items:
        # 文件存在或自填 complete 不足以放行，必须提交带范围及摘要的验收记录。
        if row.get('status')!='verified' or not row.get('evidence'):
            pending.append({'id':row['id'],'reason':row.get('reason','没有经过核验的证据')})
            continue
        proof=read(ROOT/row['evidence'])
        valid=(proof.get('requirement_id')==row['id'] and proof.get('status')=='passed'
               and proof.get('source_sha256')==source_hashes() and bool(proof.get('artifact_sha256'))
               and bool(proof.get('review_scope')))
        if valid:
            valid=all((ROOT/path).is_file() and digest(ROOT/path)==value for path,value in proof['artifact_sha256'].items())
        if not valid:
            pending.append({'id':row['id'],'reason':'验收记录缺失、过期或没有限定审查范围'})
    return pending


def refresh():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q2_2.py')],cwd=ROOT,timeout=1800)
    require(result.returncode==0,'当前源码完整回归失败，不生成新的发布候选')
    folder=ROOT/'.venv/release-runs'/uuid.uuid4().hex
    result=subprocess.run([sys.executable,str(ROOT/'run_all.py'),'--offline',
        '--q1-output-dir',str(folder/'q1'),'--q2-output-dir',str(folder/'q2'),'--report',str(PIPELINE)],cwd=ROOT,timeout=900)
    require(result.returncode in (0,2),'全入口发生运行失败')
    return {'pipeline_exit_code':result.returncode,'scope':'缺题返回 2 仅是观测结果，不等于完整交付'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['implemented','submission'],default='submission')
    parser.add_argument('--refresh',action='store_true',help='重跑完整已有业务回归和正式全入口；需要本机 Docker/MySQL')
    args=parser.parse_args()
    with EvidenceRun(ROOT/'reports/release',args.scope) as e:
        if args.refresh and not e.check('重跑当前源码与全入口',refresh):
            return 1
        e.check('当前功能回归及代码、产物绑定',lambda:inspect_regression(read(REGRESSION),e.report['source_sha256']))
        e.check('锁定依赖安装证据及适用范围',inspect_dependencies)
        e.check('真实全入口及本轮产物归属',inspect_execution)
        e.check('数据库配置修复证据适用范围',inspect_runtime_repair)
        e.check('原题与数据提交约束',inspect_protected)
        implemented=all(c['passed'] for c in e.report['checks'])
        e.report['implemented_ready']=implemented
        if args.scope=='submission':
            def submission():
                pending=pending_items(read(ROOT/'delivery_requirements.json')['requirements'])
                e.report['pending_requirements']=pending
                require(not pending,'仍有未完成或未核实的必答题与提交材料')
                execution=read(PIPELINE)
                require(execution.get('exit_code')==0 and execution.get('status')=='passed','完整全入口未通过')
                return {'mandatory_items_verified':True,'limit':'机器检查不能替代人工内容质量、理解与外部平台审查'}
            e.check('完整项目逐项交付条件',submission)
        e.report['decision']='implemented_ready' if args.scope=='implemented' and implemented else 'not_ready'
        if args.scope=='submission' and all(c['passed'] for c in e.report['checks']):
            e.report['decision']='submission_evidence_complete'
        e.save()
    print(json.dumps({'scope':args.scope,'decision':e.report['decision'],'report':str(e.path)},ensure_ascii=False))
    return 0 if e.report['status']=='passed' else 1 if not implemented else 2


if __name__=='__main__':
    raise SystemExit(main())
