"""当前唯一交付判定：局部范围可扩展，与完整项目可提交分开。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from artifact_manifest import ARTIFACTS, digest, manifest_path, source_hashes, validate_manifest, read_json
from scripts.verification_support import EvidenceRun, require, verification_source_hashes
from audit.q2_3_performance import inspect_performance

REQUIRED_PENDING={'Q2.3','Q2.4','Q3.1','Q4.1','Q5.1','DOCS','AI_LOG','COLD_START','PUBLIC_FORK','FINAL_COMMIT','HUMAN_REVIEW'}
REGRESSION_CHECKS={
    '真实 MySQL 与本地项目环境', '独立参考校准、手算、变换、错误注入与边界',
    '真实全部月份及诊断列独立复算', '真实数据直接连接的偏差与独立敏感性',
    '同模块独立题目失败隔离', '独立/总入口与真实缺输入故障',
    '九表/Q2.1/Q1 当前源码回归与最终批次复算',
}
PIPELINE=ROOT/'reports/release_execution.json'
REGRESSION=ROOT/'reports/q2_2/acceptance_latest.json'
CONTRACTS={
 'Q2.3':('q2_3','acceptance',{
  '真实 MySQL 环境','冻结口径的性能实测与适用范围','手算、连接粒度、分母、并列、截断及定向错误',
  '全部真实卖家独立复算、金额及评价规则敏感性','已有业务当前源码回归','本题正式入口与失败归属'},
  {'q2_sql_analysis/q2_3_results.json','q2_sql_analysis/q2_3_findings.md','reports/q2_3_reference.json'}),
 'Q2.4':('q2_4','acceptance',{'真实 MySQL 与 TLS 就绪','冻结 SQL、真实计时证据与手算反例','当前源码既有业务回归及默认四题入口','本题正式发布、逐州独立复算与全入口归属'},
  {'q2_sql_analysis/q2_4_results.json','q2_sql_analysis/q2_4_query_optimization.md','reports/q2_4_experiment.json'}),
 'Q3.1':('q3','acceptance',{'固定手算与拒绝有损输入','已有业务回归及默认全入口','全量独立复算、确定性、类型回读、性能和失败清单','可空价格三态、旧版不变量与独立参考拒绝语义损坏'},
  {'q3_etl_pipeline/'+p for p in ['validation_metrics.json','validation_report.md','outputs/sales_facts.parquet','outputs/customer_features.parquet','outputs/returns_log.parquet']}|{'reports/q3/nullable_price_snapshot.json','reports/q3/report_statistics_reference.json'}),
 'Q4.R1':('q4','engineering',{'预设反例、计费手算、恢复与墙钟进程终止','定向变异必须由指定反例检出','全量冻结输入、独立分流、部分状态与空标注拒绝'},
  {'.venv/q4-engineering-output/'+p for p in ['extracted_issues.json','run_metrics.json','annotation_blind.json','cost_report.md']}|{'q4_llm_extraction/pipeline_design.md','q4_llm_extraction/accuracy_evaluation.md'}),
 'Q4.PROCESSING':('q4','processing',{'真实全量、逐行证据、原始回执与累计预算时长'},
  {'q4_llm_extraction/'+p for p in ['extracted_issues.json','run_metrics.json','annotation_blind.json','cost_report.md']}),
 'Q5.1':('q5','acceptance',{'文档、情景手算与正式默认入口'},
  {'q5_system_design/real_time_pipeline_design.md','q5_system_design/design_metrics.json'}),
 'Q6':('bonus','acceptance',{'Q6.1 原文、用户轮次和重写提示区分','Q6.2 逐事实独立复算与字数边界'},
  {'bonus/q6_1_ai_collaboration.md','bonus/q6_2_business_insights.md','bonus/ACCEPTANCE.md'}),
}
REGRESSION_ARTIFACTS={'q2_sql_analysis/q2_2_results.json','q2_sql_analysis/q2_2_findings.md','reports/q2_2_reference.json'}


def read(path):
    return read_json(path)


def inspect_checks(proof,required=None):
    checks=proof.get('checks')
    require(isinstance(checks,list) and checks and all(isinstance(c,dict) and isinstance(c.get('name'),str) and c['name'] for c in checks),'检查记录缺失或结构无效')
    names=[c['name'] for c in checks]
    require(len(names)==len(set(names)),'检查记录重复')
    require(required is None or set(names)==required,'必需检查缺项或范围改变')
    require(all(c.get('passed') is True for c in checks),'检查存在未通过或非布尔状态')


def inspect_artifacts(proof,required=None):
    values=proof.get('artifact_sha256')
    require(isinstance(values,dict) and values,'缺少验收产物指纹')
    require(required is None or set(values)==required,'必需产物缺项或引用无关产物')
    for path,value in values.items():
        require(isinstance(path,str) and not Path(path).is_absolute(),'产物路径无效')
        target=(ROOT/path).resolve()
        require(target.is_relative_to(ROOT.resolve()),'产物路径越出项目')
        require(target.is_file() and isinstance(value,str) and digest(target)==value,'验收产物缺失或已改变：'+path)


def inspect_subquestion(stage,current=None,proof=None):
    folder,label,checks,artifacts=CONTRACTS[stage]
    proof=read(ROOT/f'reports/{folder}/{label}_latest.json') if proof is None else proof
    require(isinstance(proof,dict),'验收记录不是结构化对象')
    require(proof.get('status')=='passed' and proof.get('requirement_id')==stage,stage+' 没有对应范围的通过报告')
    require(proof.get('source_sha256')==(verification_source_hashes() if current is None else current),stage+' 验收源码已变化')
    require(proof.get('production_source_sha256')==source_hashes(),stage+' 生产源码已变化')
    require(isinstance(proof.get('review_scope'),str) and proof['review_scope'].strip(),'验收范围说明缺失')
    inspect_checks(proof,checks);inspect_artifacts(proof,artifacts)
    if stage=='Q4.PROCESSING':
        path=manifest_path(ROOT/'q4_llm_extraction','q4');record=read(path)
        validate_manifest(path,record['run_id'])
    return {'run_id':proof['run_id'],'scope':'具备全部必需检查、限定产物、当前源码及实际字节的程序证据'}


def inspect_regression(report, current):
    require(report.get('status')=='passed','当前功能回归未通过')
    checks=report.get('checks',[])
    require({c['name'] for c in checks}==REGRESSION_CHECKS and len(checks)==len(REGRESSION_CHECKS), '关键检查缺失、重复或范围变化；需审查验收契约')
    require(all(c.get('passed') is True for c in checks),'存在失败检查')
    require(report.get('source_sha256')==current,'功能回归源码已过期')
    inspect_artifacts(report,REGRESSION_ARTIFACTS)
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
    inspect_complete_execution(report)
    require(report.get('source_sha256')==source_hashes(),'全入口运行源码已变化')
    input_evidence=inspect_inputs()
    rows={r['stage']:r for r in report['results']}
    for stage in ('data.retail','data.olist','q1.1','q1.2','q1.3','q3','q4','q5'):
        require(rows.get(stage,{}).get('status')=='passed',f'{stage} 未成功')
    require(rows.get('q2',{}).get('status')=='passed','Q2 未完整通过')
    nested={r['stage']:r for r in rows['q2']['detail']['results']}
    for stage in ('q2.load','q2.1','q2.2','q2.3','q2.4'):
        require(nested.get(stage,{}).get('status')=='passed',f'{stage} 未成功')
    outputs=report['output_directories']; validated={}
    for stage in ARTIFACTS:
        folder=Path(outputs[stage.split('.')[0]])
        record=validate_manifest(manifest_path(folder,stage),report['run_id'])
        if stage=='q4':
            require(record['status']==rows['q4']['status'],'Q4 清单与实际入口状态不一致')
        validated[stage]={'manifest_sha256':digest(manifest_path(folder,stage)),'artifacts':record['artifacts']}
    # 再执行产生新的数据库批次；只豁免随机批次号，所有业务字段必须相等。
    for group,name in [('q1','data_quality_metrics.json'),('q1','findings_metrics.json'),
                       ('q2','q2_1_results.json'),('q2','q2_2_results.json'),('q2','q2_3_results.json'),('q2','q2_4_results.json')]:
        original=read(ROOT/('q1_data_quality' if group=='q1' else 'q2_sql_analysis')/name)
        actual=read(Path(outputs[group])/name)
        require({k:v for k,v in actual.items() if k!='load_version'}=={k:v for k,v in original.items() if k!='load_version'},f'独立回归结果与本轮正式 CLI 不一致：{name}')
    for name in ['sales_facts','customer_features','returns_log']:
        require(digest(Path(outputs['q3'])/'outputs'/(name+'.parquet'))==digest(ROOT/'q3_etl_pipeline/outputs'/(name+'.parquet')),'Q3 候选与独立复算版本不一致')
    require(digest(Path(outputs['q4'])/'extracted_issues.json')==digest(ROOT/'q4_llm_extraction/extracted_issues.json'),'Q4 默认入口与真实验证结果不同')
    return {'run_id':report['run_id'],'exit_code':report['exit_code'],'report_sha256':digest(PIPELINE),'manifests':validated,'current_inputs':input_evidence,
            'scope':'当前环境、已下载冻结输入；不是完整冷启动证明'}


def inspect_inputs():
    datasets=read(ROOT/'data_sources.json')['datasets'];targets=set()
    require(set(datasets)=={'retail','olist'},'冻结数据源缺项')
    for dataset in datasets.values():
        require(isinstance(dataset.get('files'),list) and dataset['files'],'数据源文件清单为空')
        for expected in dataset['files']:
            target=expected['target'];path=(ROOT/'data'/target).resolve()
            require(target not in targets and path.is_relative_to((ROOT/'data').resolve()),'输入路径重复或越界')
            targets.add(target)
            require(path.is_file() and path.stat().st_size==expected['bytes'] and digest(path)==expected['sha256'],'当前输入缺失或已改变：'+target)
    return {'verified_files':len(targets),'scope':'当前输入字节与未修改的冻结数据清单一致；不以旧运行记录替代当前文件'}


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


def inspect_complete_execution(report):
    require(report.get('requested_stage')=='all' and type(report.get('exit_code')) is int and report['exit_code']==0 and report.get('status')=='passed','完整全入口未通过')
    def unique_rows(items):
        require(isinstance(items,list) and all(isinstance(r,dict) and isinstance(r.get('stage'),str) for r in items),'阶段结构无效')
        require(len({r['stage'] for r in items})==len(items),'阶段重复，不能覆盖前项失败')
        return {r['stage']:r for r in items}
    rows=unique_rows(report.get('results',[]))
    required={'data.retail','data.olist','q1.1','q1.2','q1.3','q2','q3','q4','q5'}
    require(set(rows)==required and all(r.get('status')=='passed' for r in rows.values()),'完整入口缺少必答阶段或存在未通过阶段')
    nested=unique_rows(rows['q2'].get('detail',{}).get('results',[]))
    require(set(nested)=={'q2.load','q2.1','q2.2','q2.3','q2.4'} and all(r.get('status')=='passed' for r in nested.values()),'Q2 缺少必答题或未通过')
    return True


def pending_items(items):
    require({r['id'] for r in items}==REQUIRED_PENDING and len(items)==len(REQUIRED_PENDING),'提交清单缺项、重复或范围改变')
    pending=[]
    for row in items:
        # 文件存在或自填 complete 不足以放行，必须提交带范围及摘要的验收记录。
        if row.get('status')!='verified' or not row.get('evidence'):
            pending.append({'id':row['id'],'reason':row.get('reason','没有经过核验的证据')})
            continue
        try:
            path=(ROOT/row['evidence']).resolve()
            require(path.is_relative_to(ROOT.resolve()),'证据路径越出项目')
            proof=read(path)
            require(isinstance(proof,dict),'验收记录不是结构化对象')
            if row['id'] in CONTRACTS:inspect_subquestion(row['id'],proof=proof)
            else:
                require(proof.get('requirement_id')==row['id'] and proof.get('status')=='passed','验收范围或状态不符')
                require(proof.get('production_source_sha256')==source_hashes(),'生产源码已变化')
                require(isinstance(proof.get('review_scope'),str) and proof['review_scope'].strip(),'验收范围缺失')
                inspect_checks(proof);inspect_artifacts(proof)
        except (OSError,ValueError,TypeError,KeyError,AssertionError):
            pending.append({'id':row['id'],'reason':'验收记录缺失、结构不完整、过期或未满足限定审查范围'})
    return pending


def refresh():
    result=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q3.py')],cwd=ROOT,timeout=3600)
    require(result.returncode==0,'当前源码完整回归失败，不生成新的发布候选')
    # Q2.3 验证器已实际运行默认全入口，检查同一候选，避免重复导入。
    design=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q5.py')],cwd=ROOT,timeout=120)
    require(design.returncode==0,'Q5 文档交付验收失败')
    engineering=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q4.py')],cwd=ROOT,timeout=180)
    require(engineering.returncode==0,'Q4 无网络工程验收失败')
    bonus=subprocess.run([sys.executable,str(ROOT/'scripts/verify_bonus.py')],cwd=ROOT,timeout=120)
    require(bonus.returncode==0,'已提供加分题的事实复算验收失败')
    processing=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q4_live.py'),'--output-dir',str(ROOT/'q4_llm_extraction')],cwd=ROOT,timeout=180)
    require(processing.returncode==0,'Q4 真实处理证据未通过，不生成完整执行候选')
    # 先前各模块的故障回归强制无网络；此处在已验证的响应缓存上执行真实配置默认入口。
    candidate=ROOT/'.venv/release-runs'/uuid.uuid4().hex
    args=[sys.executable,str(ROOT/'run_all.py'),'--offline','--q4-live','--report',str(PIPELINE)]
    for stage in ('q1','q2','q3','q4','q5'):args.extend(['--'+stage+'-output-dir',str(candidate/stage)])
    execution=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=1800)
    require(execution.returncode==0,'最终全模块入口未成功；未用无网络分流冒充通过')
    report=read(PIPELINE)
    require(report.get('exit_code')==0,'全入口发生运行失败')
    return {'pipeline_exit_code':report['exit_code'],'scope':'当前 Q1–Q5 及加分题的程序/真实处理范围；Q4 语义与最终提交材料另行验收，不冒称无缓存全量调用'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['implemented','submission'],default='submission')
    parser.add_argument('--refresh',action='store_true',help='重跑完整已有业务回归和正式全入口；需要本机 Docker/MySQL')
    args=parser.parse_args()
    with EvidenceRun(ROOT/'reports/release',args.scope) as e:
        if args.refresh and not e.check('重跑当前源码与全入口',refresh):
            return 1
        e.check('当前功能回归及代码、产物绑定',lambda:inspect_regression(read(REGRESSION),e.report['source_sha256']))
        e.check('Q2.3 性能证据仍适用',inspect_performance)
        for stage in ('Q2.3','Q2.4','Q3.1','Q4.R1','Q4.PROCESSING','Q5.1','Q6'):
            e.check(stage+' 当前业务及默认入口',lambda name=stage:inspect_subquestion(name,e.report['source_sha256']))
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
                inspect_complete_execution(execution)
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
