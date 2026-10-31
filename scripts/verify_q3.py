"""Q3 当前验收：手算、不同匹配算法、全量逐行摘要、回读、确定性与默认入口。"""
import json
from copy import deepcopy
import time
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import publish,source_hashes,validate_manifest,manifest_path
from scripts.verification_support import EvidenceRun,require,sha256,atomic_json
from q3_etl_pipeline.pipeline import run_pipeline
from q3_etl_pipeline.reference_check import check
from scripts.q3_report_reference import check_report_statistics


def inspect_nullable_prices(folder=ROOT/'q3_etl_pipeline'):
    """重建已提交的旧版作不变量比较；再故意损坏真实产物，检查独立参考会拒绝。"""
    folder=Path(folder)
    control=check(folder)
    with tempfile.TemporaryDirectory(prefix='gekko-q3-price-') as temporary:
        base=Path(temporary);module_file=base/'q3_etl_pipeline/pipeline.py';module_file.parent.mkdir()
        old_source=subprocess.check_output(['git','show','1b32c88:q3_etl_pipeline/pipeline.py'],cwd=ROOT)
        module_file.write_bytes(old_source)
        for name in ('download_data.py','data_sources.json','requirements.txt'):
            require((ROOT/name).read_bytes()==subprocess.check_output(['git','show','1b32c88:'+name],cwd=ROOT),'旧版重建的数据解析或依赖条件改变：'+name)
        spec=importlib.util.spec_from_file_location('_q3_before_nullable_price',module_file)
        module=importlib.util.module_from_spec(spec);paths=list(sys.path)
        try:spec.loader.exec_module(module)
        finally:sys.path[:]=paths
        old_folder=base/'baseline';module.run_pipeline(ROOT/'data/online_retail_ii.csv',old_folder)
        same_hashes={}
        for name in ('sales_facts','customer_features'):
            before=sha256(old_folder/'outputs'/(name+'.parquet'));after=sha256(folder/'outputs'/(name+'.parquet'))
            require(before==after,name+' 字节改变，修复扩展字段不应改变金额或 RFM')
            same_hashes[name]=after
        old=pd.read_parquet(old_folder/'outputs/returns_log.parquet')
        actual=pd.read_parquet(folder/'outputs/returns_log.parquet')
        pd.testing.assert_frame_equal(old.drop(columns='price_mismatch'),actual.drop(columns='price_mismatch'))
        known=actual['matched_source_row'].notna()
        pd.testing.assert_series_equal(old.loc[known,'price_mismatch'],actual.loc[known,'price_mismatch'].astype(bool))
        require(actual.loc[~known,'price_mismatch'].isna().all(),'未匹配价格比较仍有已知值')
        native=pq.read_table(folder/'outputs/returns_log.parquet')['price_mismatch']
        require(native.type==pa.bool_() and native.null_count==int((~known).sum()),'Parquet 原生布尔/NULL 未保留')
        require(int(known.sum())==6303 and int(actual['price_mismatch'].dropna().sum())==217,'已知匹配或差异数量改变')
        # 只改一条未知比较为 False，其他文件原样复制；不是依靠生产校验器抓错。
        damaged=base/'damaged';(damaged/'outputs').mkdir(parents=True)
        for name in ('sales_facts','customer_features','returns_log'):
            shutil.copy2(folder/'outputs'/(name+'.parquet'),damaged/'outputs'/(name+'.parquet'))
        shutil.copy2(folder/'validation_metrics.json',damaged/'validation_metrics.json')
        changed=actual.copy();position=changed.index[~known][0]
        changed.loc[position,'price_mismatch']=False
        require(str(changed['price_mismatch'].dtype)=='boolean','损坏夹具意外改变类型，不能用类型错误冒充语义检出')
        changed.to_parquet(damaged/'outputs/returns_log.parquet',index=False)
        rejected=False
        try:check(damaged)
        except AssertionError as exc:
            require(str(exc)=='退货候选/容量/原因逐条不符独立列表删除参考','错误不是预期的逐行语义核对')
            rejected=True
        require(rejected,'独立参考接受了未知强填 False 的真实产物')
        result={'baseline_commit':'1b32c881ee3d3c605b1b10b7d2f8f39b3feb8072',
                'baseline_pipeline_sha256':hashlib.sha256(old_source).hexdigest(),
                'sales_and_rfm_byte_unchanged':same_hashes,'all_other_return_columns_unchanged':True,
                'known_price_comparisons_unchanged':True,'matched_rows':int(known.sum()),
                'price_comparison_counts':control['price_comparison_counts'],
                'native_parquet_price_type':str(native.type),'native_parquet_null_count':native.null_count,
                'independent_reference_accepted_control':True,'independent_reference_rejected_unknown_as_false':True,
                'corrupted_source_row':int(changed.loc[position,'source_row']),
                'scope':'旧版同数据重建及一类真实语义损坏拒绝；不证明其他未知错误不存在，也不认证退款真值'}
        atomic_json(ROOT/'reports/q3/nullable_price_snapshot.json',result)
        return result


def main():
    with EvidenceRun(ROOT/'reports/q3','acceptance') as e:
        def fixtures():
            r=subprocess.run([sys.executable,'-m','unittest','q3_etl_pipeline.test_pipeline','q3_etl_pipeline.test_report_statistics','-v'],cwd=ROOT,capture_output=True,text=True,timeout=60)
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
            wall_started=time.monotonic()
            actual=publish('q3',ROOT/'q3_etl_pipeline',lambda fresh:run_pipeline(ROOT/'data/online_retail_ii.csv',fresh),inputs=[ROOT/'data/online_retail_ii.csv'])
            wall_seconds=time.monotonic()-wall_started
            require(actual['under_120_seconds'] and wall_seconds<120,'本次真实运行含统计/报告未达到两分钟')
            hashes={}
            for name in ['sales_facts','customer_features','returns_log']:
                relative='outputs/'+name+'.parquet';value=sha256(ROOT/'q3_etl_pipeline'/relative)
                require(value==sha256(folder/relative),'重跑 Parquet 字节不同，不能沿用逐行参考')
                hashes[relative]=value
            statistics=check_report_statistics(ROOT/'q3_etl_pipeline')
            candidate_statistics=check_report_statistics(folder)
            claimed=json.loads((ROOT/'q3_etl_pipeline/validation_metrics.json').read_text())
            controls=[]
            for field in ('missing_rate','wrong_rate','wrong_quantile','country_coverage'):
                bad=deepcopy(claimed);summary=bad['outputs']['sales_facts']
                if field=='missing_rate':summary.pop('null_rates')
                elif field=='wrong_rate':summary['null_rates']['customer_id']=0.0
                elif field=='wrong_quantile':summary['numeric_distributions']['quantity']['p95']+=1
                else:summary['country_distribution'].pop()
                rejected=False
                try:check_report_statistics(ROOT/'q3_etl_pipeline',bad)
                except AssertionError:rejected=True
                require(rejected,'统计损坏未被独立参考拒绝：'+field)
                controls.append({'fixture_only':True,'change':field,'rejected':rejected})
            statistics_proof={'status':'passed','canonical':statistics,'candidate':candidate_statistics,
                'negative_controls':controls,'production_wall_seconds_including_reports_and_publish':wall_seconds,
                'real_metrics_unchanged_by_controls':sha256(ROOT/'q3_etl_pipeline/validation_metrics.json')==statistics['metric_file_sha256']}
            require(statistics_proof['real_metrics_unchanged_by_controls'],'损坏控制修改了真实指标')
            atomic_json(ROOT/'reports/q3/report_statistics_reference.json',statistics_proof)
            with tempfile.TemporaryDirectory(prefix='gekko-q3-fail-') as tmp:
                target=Path(tmp)
                r=subprocess.run([sys.executable,str(ROOT/'q3_etl_pipeline/pipeline.py'),'--input',str(target/'missing.csv'),'--output-dir',str(target)],cwd=target,capture_output=True,text=True,timeout=30)
                require(r.returncode!=0,'独立 CLI 缺输入未失败')
                state=json.loads(manifest_path(target,'q3').read_text());require(state['status']=='failed','失败清单未写出')
            return {'pipeline_run_id':top['run_id'],'reference':reference,'production_seconds':actual['seconds'],'production_wall_seconds_including_reports_and_publish':wall_seconds,'report_statistics':statistics,'parquet_sha256':hashes,
                'sensitivity':actual['return_candidate_sensitivity'],'scope':'固定业务政策与候选匹配；不是业务真值或净退款认证'}
        if not e.check('全量独立复算、确定性、类型回读、性能和失败清单',full):return 1
        if not e.check('可空价格三态、旧版不变量与独立参考拒绝语义损坏',inspect_nullable_prices):return 1
        e.report.update(requirement_id='Q3.1',production_source_sha256=source_hashes(),review_scope='原始 CSV 独立逐行摘要/客户集合/列表删除候选，正式默认入口与 Parquet 回读；政策假设仍公开')
        names=['validation_metrics.json','validation_report.md','outputs/sales_facts.parquet','outputs/customer_features.parquet','outputs/returns_log.parquet']
        e.report['artifact_sha256']={str((ROOT/'q3_etl_pipeline'/p).relative_to(ROOT)):sha256(ROOT/'q3_etl_pipeline'/p) for p in names}
        e.report['artifact_sha256']['reports/q3/nullable_price_snapshot.json']=sha256(ROOT/'reports/q3/nullable_price_snapshot.json')
        e.report['artifact_sha256']['reports/q3/report_statistics_reference.json']=sha256(ROOT/'reports/q3/report_statistics_reference.json')
        e.save()
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
