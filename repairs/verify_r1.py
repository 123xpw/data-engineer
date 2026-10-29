"""R1：真实反例重放、优化模式拒绝及已有完整回归。"""

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verification_support import EvidenceRun,require,sha256


def main():
    with EvidenceRun(ROOT/'reports/repairs/r1','acceptance') as e:
        e.report['repair_contract_sha256']=sha256(ROOT/'repairs/R1_ACCEPTANCE.md')
        e.report['repair_script_sha256']=sha256(__file__);e.save()
        def replay():
            with tempfile.TemporaryDirectory(prefix='gekko-r1-') as folder:
                copy=Path(folder)
                for name in ('scripts','tests','q1_data_quality','q2_sql_analysis'):
                    shutil.copytree(ROOT/name,copy/name,ignore=shutil.ignore_patterns('__pycache__'))
                for p in ROOT.glob('*.py'):shutil.copyfile(p,copy/p.name)
                for name in ('requirements.txt','data_sources.json','VALIDATION_GATES.md'):
                    shutil.copyfile(ROOT/name,copy/name)
                (copy/'.venv').mkdir();shutil.copyfile(ROOT/'.venv/mysql-ca.pem',copy/'.venv/mysql-ca.pem')
                env=os.environ.copy();env.pop('PYTHONOPTIMIZE',None)
                env['GEKKO_MYSQL_ENV_FILE']=str(ROOT/'.env')
                def call(script,flags=(),extra_env=None):
                    result=subprocess.run([sys.executable,*flags,str(copy/script)],cwd=copy,env={**env,**(extra_env or {})},capture_output=True,text=True,timeout=60)
                    return result
                script='scripts/check_q2_2_cases.py';report=copy/'reports/q2_2/sql_cases_latest.json'
                good=call(script);require(good.returncode==0,'正确 SQL 未通过')
                good_report=json.loads(report.read_text());require(good_report['status']=='passed','正确 SQL 报告错误')
                differences=good_report['checks'][0]['evidence']['mutations']['omit_freight']['differences']
                require(any(x['field']=='delivered_gmv' for x in differences),'未保存实际金额差异')
                sql=copy/'q2_sql_analysis/q2_2_monthly_metrics.sql'
                sql.write_text(sql.read_text().replace('SUM(price + freight_value)','SUM(price)'))
                bad=call(script);bad_report=json.loads(report.read_text())
                require(bad.returncode!=0 and bad_report['status']=='failed','普通模式放过漏运费 SQL')
                require(bad_report['checks'][0].get('error')=='基础手算结果不同','不是数值检查拒绝')
                modes=[]
                for flags,extra in [(('-O',),{}),(('-OO',),{}),((),{'PYTHONOPTIMIZE':'1'}),((),{'PYTHONOPTIMIZE':'2'})]:
                    rejected=call(script,flags,extra);observed=json.loads(report.read_text())
                    require(rejected.returncode!=0 and observed['status']=='failed','优化模式没有失败')
                    require(observed['checks'][0]['name']=='验收运行模式','优化模式先执行了业务检查')
                    modes.append({'flags':list(flags),'environment':extra,'exit_code':rejected.returncode,
                                  'optimization_level':observed['python_optimization_level'],'status':observed['status']})
                entries=[]
                for path in (copy/'scripts').glob('*.py'):
                    tree=ast.parse(path.read_text())
                    if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='EvidenceRun' for n in ast.walk(tree)):
                        rejected=call(str(path.relative_to(copy)),('-O',))
                        require(rejected.returncode!=0 and '禁止使用优化模式验收' in rejected.stderr,f'{path.name} 未明确拒绝优化模式')
                        entries.append(path.name)
                return {'correct_sql_passed':True,'missing_freight_rejected':True,'actual_difference':differences,
                        'optimized_modes':modes,'all_evidence_entrypoints_rejected':sorted(entries),
                        'scope':'临时副本与真实 MySQL 临时表；不修改正式业务 SQL'}
        if not e.check('正确对照、真实漏运费与全部验收入口优化模式',replay):return 1
        def regression():
            r=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q2_2.py')],cwd=ROOT,capture_output=True,text=True,timeout=900)
            require(r.returncode==0,r.stdout[-1200:])
            report=json.loads((ROOT/'reports/q2_2/acceptance_latest.json').read_text())
            require(report['status']=='passed' and report['source_sha256']==e.report['source_sha256'],'回归版本不一致')
            return {'q22_full_regression':report['run_id']}
        e.check('当前版本全部已实现模块回归',regression)
    print(e.path)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
