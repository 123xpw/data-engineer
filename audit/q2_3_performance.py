"""冻结 Q2.3 口径，比较连接顺序；只读业务表，逐轮保存真实计时和完整结果核对。"""
import argparse
from decimal import Decimal
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import digest
from q2_sql_analysis.mysql_runtime import ensure_mysql,connect
from q2_sql_analysis.load_olist import require_ready,warnings_fail
from scripts import check_q2_3_cases as cases
from scripts.q2_3_reference import read_reference
from scripts.verification_support import EvidenceRun,require

BASELINE=ROOT/'audit/fixtures/q2_3_baseline_0f40889.sql'
CANDIDATE=ROOT/'audit/fixtures/q2_3_materialized_candidate.sql'
CONTRACT=ROOT/'audit/ACCEPTANCE_Q2_3_PERFORMANCE.md'
CONTEXT=['requirements.txt','data_sources.json','q2_sql_analysis/catalog.py',
         'q2_sql_analysis/load_olist.py','q2_sql_analysis/mysql_runtime.py',
         'scripts/q2_3_reference.py','scripts/check_q2_3_cases.py']
ORDER=[(1,'baseline'),(1,'candidate'),(2,'candidate'),(2,'baseline'),(3,'baseline'),(3,'candidate')]

def summarize(observations):
    """拒绝缺轮、重复、重排、非有限耗时及不满足预设收益的记录。"""
    require([(r.get('round'),r.get('query')) for r in observations]==ORDER,'测量轮次、顺序或数量不符预先协议')
    for row in observations:
        value=row.get('seconds')
        require(type(value) in (int,float) and math.isfinite(value) and value>0,'耗时不是正有限数')
        require(row.get('status')=='passed' and row.get('all_fields_equal') is True,'测量结果未通过全部字段核对')
    values={name:[r['seconds'] for r in observations if r['query']==name] for name in ('baseline','candidate')}
    medians={name:statistics.median(v) for name,v in values.items()}
    require(medians['candidate']<=medians['baseline']*0.8,'中位耗时改善不足预定 20%')
    require(max(values['candidate'])<min(values['baseline']),'候选与基线耗时区间重叠，暂不采用')
    return {'median_seconds':medians,'baseline_over_candidate':medians['baseline']/medians['candidate'],
            'candidate_max_seconds':max(values['candidate']),'baseline_min_seconds':min(values['baseline'])}

def inspect_performance(proof_path=None):
    """发布端仅复用未改变的冻结 SQL、数据、类型视图及计时协议证据。"""
    proof=json.loads(Path(proof_path or ROOT/'reports/q2_3/performance_latest.json').read_text())
    require(proof.get('status')=='passed' and proof.get('requirement_id')=='Q2.3.PERFORMANCE','没有本题性能实验通过证据')
    require(proof.get('benchmark_sha256')==digest(Path(__file__)),'性能协议代码已改变，需重新实测')
    require(proof.get('contract_sha256')==digest(CONTRACT),'性能验收契约已改变')
    for name in ('baseline','candidate'):
        path=BASELINE if name=='baseline' else CANDIDATE
        require(proof['sql_sha256'][name]==digest(path),'实测 SQL 已变化')
    require((ROOT/'q2_sql_analysis/q2_3_top_sellers.sql').read_bytes()==CANDIDATE.read_bytes(),'生产 SQL 与已实测候选不同')
    for name,value in proof['context_sha256'].items():
        require(digest(ROOT/name)==value,'类型视图、依赖或参考协议已变化：'+name)
    require(set(proof['context_sha256'])==set(CONTEXT),'性能上下文指纹缺项')
    expected={str(p.relative_to(ROOT)) for p in (ROOT/'data/olist').glob('*.csv')}
    require(set(proof['input_sha256'])==expected and len(expected)==9,'性能输入清单不完整')
    for name,value in proof['input_sha256'].items():require(digest(ROOT/name)==value,'性能输入已改变')
    result=summarize(proof['observations'])
    require(proof.get('statistics')==result,'性能汇总与原始观测不一致')
    require(proof.get('top20_equal') is True and proof.get('batch_unchanged') is True,'TOP20 或同批次核对不完整')
    require(set(proof.get('actual_plans',{}))=={'baseline','candidate'} and all(proof['actual_plans'].values()),'缺少双方实际迭代器计划')
    return {'run_id':proof['run_id'],**result,
            'scope':'复用相同 SQL、类型视图、冻结数据与依赖的本机暖缓存三轮对照；当前入口另验，非跨环境速度保证'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot',action='store_true',help='只做候选正确性与计划预检，不作采用依据')
    args=parser.parse_args()
    with EvidenceRun(ROOT/'reports/q2_3','performance_pilot' if args.pilot else 'performance') as e:
        e.report.update(requirement_id='Q2.3.PERFORMANCE_PILOT' if args.pilot else 'Q2.3.PERFORMANCE',
                        benchmark_sha256=digest(Path(__file__)),contract_sha256=digest(CONTRACT),
                        context_sha256={name:digest(ROOT/name) for name in CONTEXT},
                        input_sha256={str(p.relative_to(ROOT)):digest(p) for p in sorted((ROOT/'data/olist').glob('*.csv'))},
                        sql_sha256={'baseline':digest(BASELINE),'candidate':digest(CANDIDATE)},
                        adoption_threshold={'candidate_median_max_fraction':0.8,'candidate_max_below_baseline_min':True})
        baseline=BASELINE.read_text();candidate=CANDIDATE.read_text()
        def fixed():
            frozen=subprocess.check_output(['git','show','0f40889:q2_sql_analysis/q2_3_top_sellers.sql'],cwd=ROOT)
            require(BASELINE.read_bytes()==frozen,'基线不是指定提交的原样 SQL')
            expected=baseline
            for name in ('orders o','sellers s','customers c'):
                before='    JOIN '+name+' ON '
                require(expected.count(before)==1,'三处预期内连接不唯一')
                expected=expected.replace(before,'    STRAIGHT_JOIN '+name+' ON ')
            require(expected.count('    SELECT seller_id, seller_state,')==1,'事实物化提示目标不唯一')
            expected=expected.replace('    SELECT seller_id, seller_state,','    SELECT /*+ NO_MERGE(facts) */ seller_id, seller_state,')
            require(expected==candidate,'候选改变了约定之外的 SQL 内容')
            checks={}
            for name,path in [('baseline',BASELINE),('candidate',CANDIDATE)]:
                with patch.object(cases,'SQL',path):checks[name]=cases.check_cases()
            return {'mysql':ensure_mysql(),'cases':checks,'only_three_inner_join_operators_and_one_materialization_hint_changed':True}
        # 先初始化 TLS；手算函数随后只使用自己的连接级临时表。
        if not e.check('真实 MySQL 与 TLS 就绪',ensure_mysql):return 1
        if not e.check('基线冻结、变更范围及两版手算和错误注入',fixed):return 1
        reference=read_reference();expected=reference['all_sellers']
        integer_fields={key for row in expected for key,value in row.items() if type(value) is int}
        def rows(connection,sql,wanted):
            with connection.cursor() as cur:
                cur.execute(sql);names=[d[0] for d in cur.description];raw=cur.fetchall()
            warnings_fail(connection)
            actual=[]
            for raw_row in raw:
                item={}
                for key,value in zip(names,raw_row):
                    if isinstance(value,Decimal):
                        if key in integer_fields:
                            require(value==value.to_integral_value(),'计数字段非整数')
                            value=int(value)
                        else:value=str(value)
                    item[key]=value
                actual.append(item)
            require(actual==wanted,'全部行、字段或稳定排序不符独立 CSV 参考')
            return actual
        def measure():
            queries={'baseline':baseline.replace(' LIMIT 20',''),'candidate':candidate.replace(' LIMIT 20','')}
            e.report['observations']=[];e.report['estimated_plans']={};e.report['actual_plans']={};e.save()
            with connect() as connection,connection.cursor() as cur:
                cur.execute("SELECT GET_LOCK('gekko_olist_loader',5)")
                require(cur.fetchone()[0]==1,'另有导入或性能实验，拒绝混合测量')
                try:
                    version=require_ready(connection);e.report['load_version']=version
                    cur.execute('SET SESSION MAX_EXECUTION_TIME=180000')
                    cur.execute('SELECT VERSION(),@@optimizer_switch,@@join_buffer_size,@@tmp_table_size,@@max_heap_table_size,@@innodb_buffer_pool_size')
                    values=cur.fetchone();e.report['server_settings']=dict(zip(['version','optimizer_switch','join_buffer_size','tmp_table_size','max_heap_table_size','innodb_buffer_pool_size'],values))
                    for name,sql in queries.items():
                        cur.execute('EXPLAIN FORMAT=JSON '+sql);e.report['estimated_plans'][name]=json.loads(cur.fetchone()[0])
                        cur.execute('SHOW WARNINGS')
                        warnings=cur.fetchall()
                        require(all(row[0]=='Note' and row[1]==1003 for row in warnings),'计划出现提示警告或错误')
                    e.save()
                    start=time.perf_counter();actual=rows(connection,queries['candidate'],expected)
                    e.report['candidate_pilot']={'seconds':round(time.perf_counter()-start,6),'sellers':len(actual),'all_fields_equal':True};e.save()
                    if not args.pilot:
                        for name,sql in queries.items():
                            e.report['active_query']={'phase':'warmup_analyze','query':name};e.save()
                            cur.execute('EXPLAIN ANALYZE '+sql);e.report['actual_plans'][name]='\n'.join(r[0] for r in cur.fetchall())
                            warnings_fail(connection);e.save();print('预热与真实计划：'+name,flush=True)
                        for round_no,name in ORDER:
                            require(require_ready(connection)==version,'测量中批次改变')
                            e.report['active_query']={'phase':'measured','round':round_no,'query':name};e.save()
                            start=time.perf_counter();actual=rows(connection,queries[name],expected)
                            row={'round':round_no,'query':name,'seconds':round(time.perf_counter()-start,6),
                                 'status':'passed','sellers':len(actual),'all_fields_equal':True}
                            e.report['observations'].append(row);e.save();print(json.dumps(row,ensure_ascii=False),flush=True)
                        e.report['statistics']=summarize(e.report['observations'])
                    rows(connection,candidate,reference['top20'])
                    frozen=json.loads(subprocess.check_output(['git','show','0f40889:q2_sql_analysis/q2_3_results.json'],cwd=ROOT))
                    require(reference['top20']==frozen['sellers'],'当前原始 CSV TOP20 与旧规范结果不同')
                    e.report['top20_equal']=True;e.report['batch_unchanged']=require_ready(connection)==version
                    require(e.report['batch_unchanged'],'实验结束时批次改变')
                    require(e.report['sql_sha256']=={'baseline':digest(BASELINE),'candidate':digest(CANDIDATE)},'实验中 SQL 已变化')
                    e.report['active_query']=None;e.save()
                finally:
                    cur.execute("SELECT RELEASE_LOCK('gekko_olist_loader')")
            return {'sellers':len(expected),'top20_equal':True,'same_batch':True,
                    'statistics':e.report.get('statistics'),'pilot_only':args.pilot,
                    'scope':'当前冻结规模本机暖缓存；预热 ANALYZE 不计入比值，不能推断冷启动或百倍规模'}
        if not e.check('候选全量预检' if args.pilot else '独立全量复算、实际计划及交替三轮计时',measure):return 1
        e.report['artifact_sha256']={str(p.relative_to(ROOT)):digest(p) for p in (BASELINE,CANDIDATE,CONTRACT)}
        e.report['review_scope']='连接顺序的同口径实测；不是模型、真人质量或跨环境性能认证';e.save()
    return 0 if e.report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
