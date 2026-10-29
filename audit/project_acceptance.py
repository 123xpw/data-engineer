"""从提交副本开展交付审查；独立记录观测，不复用原有 passed 判定器。"""

from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    run_id=uuid.uuid4().hex
    out=ROOT/'reports/project_audit'/run_id;out.mkdir(parents=True)
    baseline=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report={'run_id':run_id,'status':'running','baseline_commit':baseline,
            'audit_script_sha256':digest(__file__),'started_utc':datetime.now(timezone.utc).isoformat(),'experiments':[]}
    secrets=[]
    if (ROOT/'.env').exists():
        secrets=[s.split('=',1)[1] for s in (ROOT/'.env').read_text().splitlines() if s.startswith(('MYSQL_PASSWORD=','MYSQL_ROOT_PASSWORD='))]
    def redact(text):
        for value in secrets:
            text=text.replace(value,'[凭据已隐去]')
        return text
    def save():
        (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        (ROOT/'reports/project_audit/latest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def record(name,value):
        report['experiments'].append({'name':name,**value});save()
        print(name+': '+json.dumps(value,ensure_ascii=False)[:1000],flush=True)
    def run(name,args,cwd,env,timeout):
        start=time.monotonic()
        try:
            r=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
            stdout,stderr,code,timed_out=r.stdout,r.stderr,r.returncode,False
        except subprocess.TimeoutExpired as exc:
            stdout=exc.stdout or '';stderr=exc.stderr or ''
            if isinstance(stdout,bytes):stdout=stdout.decode(errors='replace')
            if isinstance(stderr,bytes):stderr=stderr.decode(errors='replace')
            code=None;timed_out=True
        (out/(name+'.stdout.txt')).write_text(redact(stdout))
        (out/(name+'.stderr.txt')).write_text(redact(stderr))
        return {'exit_code':code,'timed_out':timed_out,'seconds':round(time.monotonic()-start,3),
                'stdout_file':name+'.stdout.txt','stderr_file':name+'.stderr.txt'}
    save()
    try:
        with tempfile.TemporaryDirectory(prefix='gekko-project-review-') as folder:
            temp=Path(folder);copy=temp/'submitted';copy.mkdir()
            archive=temp/'submission.tar'
            subprocess.run(['git','archive','--format=tar','--output',str(archive),baseline],cwd=ROOT,check=True)
            with tarfile.open(archive) as stream:
                stream.extractall(copy,filter='data')
            environment=os.environ.copy();environment.pop('PYTHONPATH',None);environment.pop('PYTHONOPTIMIZE',None)
            environment['GEKKO_MYSQL_ENV_FILE']=str(ROOT/'.env')
            expected=['q2_sql_analysis/q2_3_top_sellers.sql','q3_etl_pipeline/pipeline.py',
                      'q4_llm_extraction/extract_reviews.py','q4_llm_extraction/prompt_template.txt',
                      'q4_llm_extraction/extracted_issues.json','q4_llm_extraction/pipeline_design.md',
                      'q4_llm_extraction/cost_report.md','q4_llm_extraction/accuracy_evaluation.md']
            templates=['q2_sql_analysis/q2_4_query_optimization.md','q5_system_design/real_time_pipeline_design.md',
                       'bonus/q6_1_ai_collaboration.md','bonus/q6_2_business_insights.md']
            record('交付文件盘点',{'missing_required_paths':[p for p in expected if not (copy/p).exists()],
                'template_markers':{p:sum((copy/p).read_text().count(x) for x in ('候选人请填写','候选人请在此填写','候选人填写','TODO')) for p in templates},
                'scope':'静态缺项，不把占位词计数当作得分'})
            units=run('submitted_unit_tests',[sys.executable,'-m','unittest','discover','-s','tests','-v'],copy,environment,120)
            record('提交副本单元测试',units)
            args=[sys.executable,str(copy/'run_all.py'),'--offline','--data-dir',str(ROOT/'data'),
                  '--q1-output-dir',str(temp/'q1'),'--q2-output-dir',str(temp/'q2'),'--report',str(temp/'all.json')]
            full=run('submitted_all',args,temp,environment,420)
            if (temp/'all.json').exists():
                full['run_report']=json.loads((temp/'all.json').read_text())
                (out/'all_run.json').write_bytes((temp/'all.json').read_bytes())
            record('提交副本完整入口',full)
            independent={}
            for label,path in [('q1.3','q1_data_quality/q1_strategy.py'),('q2.1','q2_sql_analysis/q2_1.py'),('q2.2','q2_sql_analysis/q2_2.py')]:
                cmd=[sys.executable,str(copy/path),'--output-dir',str(temp/('direct-'+label))]
                if label.startswith('q2'):cmd.append('--skip-load')
                independent[label]=run('direct_'+label,cmd,temp,environment,90)
            record('无需旧验收报告的直接入口',independent)
            artifact=temp/'q2/q2_2_results.json';before=digest(artifact) if artifact.exists() else None
            fail=run('missing_input',[sys.executable,str(copy/'run_all.py'),'--stage','q2.2','--data-dir',str(temp/'absent'),
                      '--q2-output-dir',str(temp/'q2'),'--report',str(temp/'failed.json')],temp,environment,60)
            fail['previous_result_still_exists']=artifact.exists()
            fail['previous_result_unchanged']=before is not None and artifact.exists() and before==digest(artifact)
            if (temp/'failed.json').exists():fail['run_report']=json.loads((temp/'failed.json').read_text())
            record('失败后的旧结果归属',fail)
            # 只修改已导出的临时副本，正常与优化模式使用完全相同的错误 SQL。
            sql_path=copy/'q2_sql_analysis/q2_2_monthly_metrics.sql';original=sql_path.read_text()
            if 'SUM(price + freight_value)' not in original:
                raise RuntimeError('错误注入定位失败')
            sql_path.write_text(original.replace('SUM(price + freight_value)','SUM(price)'))
            normal=run('wrong_sql_normal',[sys.executable,str(copy/'scripts/check_q2_2_cases.py')],temp,environment,60)
            normal_report=json.loads((copy/'reports/q2_2/sql_cases_latest.json').read_text())
            optimized=run('wrong_sql_optimized',[sys.executable,'-O',str(copy/'scripts/check_q2_2_cases.py')],temp,environment,60)
            optimized_report=json.loads((copy/'reports/q2_2/sql_cases_latest.json').read_text())
            (out/'wrong_sql_normal_report.json').write_text(json.dumps(normal_report,ensure_ascii=False,indent=2)+'\n')
            (out/'wrong_sql_optimized_report.json').write_text(json.dumps(optimized_report,ensure_ascii=False,indent=2)+'\n')
            record('错误 SQL 对验证器的反向实验',{'mutation':'SUM(price + freight_value) -> SUM(price)',
                   'normal':normal,'normal_claim':normal_report['status'],'optimized':optimized,
                   'optimized_claim':optimized_report['status'],'synthetic_only':True,
                   'limitation':'-O 是非默认运行模式；不表示普通 Python 的已有业务结果错误'})
            sql_path.write_text(original)
            # 既有同名项目容器中，不注入原工作区私有配置：不改变该容器密码或数据。
            no_config=environment.copy();no_config.pop('GEKKO_MYSQL_ENV_FILE',None)
            bootstrap=run('without_private_config',[sys.executable,str(copy/'q2_sql_analysis/mysql_runtime.py')],temp,no_config,115)
            bootstrap['fresh_local_config_created']=(copy/'.env').exists()
            bootstrap['scope']='同一宿主机已有项目容器，新 checkout 没有原 .env；不是全新宿主机'
            record('不注入原私有配置的副本',bootstrap)
            # 在原 Git 工作区执行历史 gate，避免把缺 .git 的归档格式混入结论。
            gate=run('legacy_stage_gate',[sys.executable,str(ROOT/'scripts/verify_stage_gate.py')],ROOT,environment,120)
            gate['checks']=json.loads((ROOT/'reports/hardening/stage_gate_latest.json').read_text())['checks']
            record('当前源码实际执行旧门槛',gate)
            report['environment_scope']={'python':sys.version.split()[0],'source':'git archive of baseline_commit',
                'dependencies':'复用已有虚拟环境，未声称本轮新装依赖','data':'读取原工作区冻结数据，未重新下载',
                'mysql':'复用本机项目实例；完整入口重新导入；未建立新服务器'}
        report['status']='completed'
        report['release_verdict']='not_ready'
        report['verdict_basis']='必答实现/材料缺失且完整入口不成功；其它发现按实际证据另列'
        report['finished_utc']=datetime.now(timezone.utc).isoformat();save()
    except Exception as exc:
        report['status']='audit_interrupted';report['error']=type(exc).__name__;save()
        raise
    print(out/'results.json')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
