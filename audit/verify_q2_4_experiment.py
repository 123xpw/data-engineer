"""仅在其它数据库验收结束后运行：三查询、独立复算、真实计时和实际计划。"""
from decimal import Decimal
import json
from pathlib import Path
import statistics
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from audit.q2_4_experiment import ORIGINAL,EQUIVALENT,CORRECTED,reference,hand_probe,result_rows
from q2_sql_analysis.mysql_runtime import ensure_mysql,connect
from q2_sql_analysis.load_olist import require_ready,warnings_fail
from scripts.verification_support import EvidenceRun,require,sha256,atomic_json


def main():
    with EvidenceRun(ROOT/'reports/q2_4','experiment') as e:
        e.report['experiment_sha256']=sha256(ROOT/'audit/q2_4_experiment.py')
        e.report['verifier_sha256']=sha256(Path(__file__))
        if not e.check('实际 MySQL 与固定反例',lambda:{'mysql':ensure_mysql(),'hand':hand_probe()}):return 1
        ref=reference();atomic_json(ROOT/'reports/q2_4_reference.json',ref)
        def experiment():
            observations=[];plans={};actual_plans={};queries={'original':ORIGINAL,'equivalent':EQUIVALENT,'corrected':CORRECTED}
            with connect() as c,c.cursor() as cur:
                cur.execute("SELECT GET_LOCK('gekko_olist_loader',5)");require(cur.fetchone()[0]==1,'另有导入活动，拒绝混合测量')
                version=require_ready(c)
                cur.execute('SET SESSION MAX_EXECUTION_TIME=90000')
                def measured(name,round_no):
                    start=time.perf_counter()
                    try:
                        actual=result_rows(c,queries[name]);warnings_fail(c)
                        wanted=ref['corrected' if name=='corrected' else 'original']
                        require(actual==wanted,f'{name} 实测结果不符独立 CSV 复算')
                        item={'query':name,'round':round_no,'seconds':round(time.perf_counter()-start,6),'status':'passed','states':len(actual)}
                    except Exception as exc:
                        code=exc.args[0] if exc.args else None
                        if code==3024:
                            item={'query':name,'round':round_no,'seconds':round(time.perf_counter()-start,6),'status':'timeout','server_limit_ms':90000}
                        else:raise
                    observations.append(item);e.report['observations']=observations;e.save()
                    return item
                for name,sql in queries.items():
                    cur.execute('EXPLAIN FORMAT=JSON '+sql);plans[name]=json.loads(cur.fetchone()[0])
                    measured(name,'warmup')
                for number in range(3):
                    sequence=list(queries) if number%2==0 else list(reversed(queries))
                    for name in sequence:measured(name,number+1)
                for name,sql in queries.items():
                    if all(x['status']=='passed' for x in observations if x['query']==name):
                        cur.execute('EXPLAIN ANALYZE '+sql);actual_plans[name]='\n'.join(r[0] for r in cur.fetchall())
                require(require_ready(c)==version,'测量中数据库批次改变')
                cur.execute("SELECT RELEASE_LOCK('gekko_olist_loader')")
            medians={name:statistics.median(x['seconds'] for x in observations if x['query']==name and x['round']!='warmup')
                for name in queries if all(x['status']=='passed' for x in observations if x['query']==name)}
            require('equivalent' in medians and 'corrected' in medians,'候选查询存在超时，不能交付为可运行结果')
            result={'version':version,'target_orders':ref['target_orders'],'states':len(ref['corrected']),
                'observations':observations,'median_seconds':medians,
                'equivalent_speedup':medians['original']/medians['equivalent'] if 'original' in medians else None,
                'original_reference':ref['original'],'corrected_reference':ref['corrected'],
                'estimated_plans':plans,'actual_iterator_plans':actual_plans,
                'limits':'当前本机与冻结规模，暖缓存交替顺序、各三轮；非冷启动、非百倍数据。估计计划不是实际扫描行数。修正版改变评分/金额语义，不用于纯优化倍数。'}
            atomic_json(ROOT/'reports/q2_4_experiment.json',result)
            return {'version':version,'target_orders':ref['target_orders'],'states':len(ref['corrected']),
                'median_seconds':medians,'equivalent_speedup':result['equivalent_speedup'],
                'artifact':'reports/q2_4_experiment.json','limits':result['limits']}
        e.check('三查询真实结果、交替计时与实际迭代器计划',experiment)
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
