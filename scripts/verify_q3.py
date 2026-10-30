"""Q3 当前验收：手算、不同匹配算法、全量逐行摘要、回读、确定性与默认入口。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import publish,source_hashes,validate_manifest,manifest_path
from scripts.verification_support import EvidenceRun,require,sha256,atomic_json
from q3_etl_pipeline.pipeline import run_pipeline
from q3_etl_pipeline.reference_check import check


def main():
    with EvidenceRun(ROOT/'reports/q3','acceptance') as e:
        def fixtures():
            r=subprocess.run([sys.executable,'-m','unittest','q3_etl_pipeline.test_pipeline','-v'],cwd=ROOT,capture_output=True,text=True,timeout=60)
            require(r.returncode==0,r.stderr[-1800:]);return {'fixed_samples':'手算金额/RFM、时间、匿名、容量、部分退货、异常 C 单、特殊商品'}
        if not e.check('固定手算与拒绝有损输入',fixtures):return 1
        def prior():
            r=subprocess.run([sys.executable,str(ROOT/'scripts/verify_q2_4.py')],cwd=ROOT,capture_output=True,text=True,timeout=2400)
            require(r.returncode==0,r.stdout[-1800:]+r.stderr[-500:])
            proof=json.loads((ROOT/'reports/q2_4/acceptance_latest.json').read_text());require(proof['source_sha256']==e.report['source_sha256'],'既有回归不是当前源码')
            return {'run_id':proof['run_id'],'scope':'当前 Q1/Q2 四题与默认入口，Q4 仍明确未完成'}
        if not e.check('已有业务回归及默认全入口',prior):return 1
        def full():
            top=json.loads((ROOT/'reports/release_execution.json').read_text());folder=Path(top['output_directories']['q3'])
            require(next(r for r in top['results'] if r['stage']=='q3')['status']=='passed','默认入口未完成 Q3')
            validate_manifest(manifest_path(folder,'q3'),top['run_id'])
            reference=check(folder);atomic_json(ROOT/'reports/q3_reference.json',reference)
            actual=publish('q3',ROOT/'q3_etl_pipeline',lambda fresh:run_pipeline(ROOT/'data/online_retail_ii.csv',fresh),inputs=[ROOT/'data/online_retail_ii.csv'])
            require(actual['under_120_seconds'],'本次真实运行未达到两分钟')
            hashes={}
            for name in ['sales_facts','customer_features','returns_log']:
                relative='outputs/'+name+'.parquet';value=sha256(ROOT/'q3_etl_pipeline'/relative)
                require(value==sha256(folder/relative),'重跑 Parquet 字节不同，不能沿用逐行参考')
                hashes[relative]=value
            with tempfile.TemporaryDirectory(prefix='gekko-q3-fail-') as tmp:
                target=Path(tmp)
                r=subprocess.run([sys.executable,str(ROOT/'q3_etl_pipeline/pipeline.py'),'--input',str(target/'missing.csv'),'--output-dir',str(target)],cwd=target,capture_output=True,text=True,timeout=30)
                require(r.returncode!=0,'独立 CLI 缺输入未失败')
                state=json.loads(manifest_path(target,'q3').read_text());require(state['status']=='failed','失败清单未写出')
            return {'pipeline_run_id':top['run_id'],'reference':reference,'production_seconds':actual['seconds'],'parquet_sha256':hashes,
                'sensitivity':actual['return_candidate_sensitivity'],'scope':'固定业务政策与候选匹配；不是业务真值或净退款认证'}
        if not e.check('全量独立复算、确定性、类型回读、性能和失败清单',full):return 1
        e.report.update(requirement_id='Q3.1',production_source_sha256=source_hashes(),review_scope='原始 CSV 独立逐行摘要/客户集合/列表删除候选，正式默认入口与 Parquet 回读；政策假设仍公开')
        names=['validation_metrics.json','validation_report.md','outputs/sales_facts.parquet','outputs/customer_features.parquet','outputs/returns_log.parquet']
        e.report['artifact_sha256']={str((ROOT/'q3_etl_pipeline'/p).relative_to(ROOT)):sha256(ROOT/'q3_etl_pipeline'/p) for p in names}
        e.save()
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
