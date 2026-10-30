"""Q5 文档交付验收：字数、情景计算、图和默认入口一致；不冒充压测。"""
from decimal import Decimal
import json
from pathlib import Path
import sys
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import publish,source_hashes,validate_manifest,manifest_path
from q5_system_design.design import deliver,scenario,SOURCE
from scripts.verification_support import EvidenceRun,require,sha256


def main():
    with EvidenceRun(ROOT/'reports/q5','acceptance') as e:
        def document():
            result=publish('q5',ROOT/'q5_system_design',deliver)
            current=scenario();small=scenario(orders_per_day=100000)
            require(Decimal(current['annual_all_review_cost_usd'])==Decimal(114975),'年度成本手算不一致')
            require(Decimal(current['annual_routed_cost_usd'])==Decimal(9198),'分流情景手算不一致')
            require(Decimal(small['annual_all_review_cost_usd'])*10==Decimal(current['annual_all_review_cost_usd']),'容量情景不随订单量线性变化')
            top=json.loads((ROOT/'reports/release_execution.json').read_text());folder=Path(top['output_directories']['q5'])
            require(next(r for r in top['results'] if r['stage']=='q5')['status']=='passed','默认入口未交付设计文档')
            validate_manifest(manifest_path(folder,'q5'),top['run_id'])
            require(sha256(folder/SOURCE.name)==sha256(SOURCE),'默认文档与独立入口不一致')
            with tempfile.TemporaryDirectory(prefix='gekko-q5-cli-') as name:
                target=Path(name)
                process=subprocess.run([sys.executable,str(ROOT/'q5_system_design/design.py'),'--output-dir',str(target)],cwd=target,capture_output=True,text=True,timeout=30)
                require(process.returncode==0,'独立文档 CLI 失败')
                require(sha256(target/SOURCE.name)==sha256(SOURCE),'独立 CLI 文档不同')
                direct=json.loads(manifest_path(target,'q5').read_text());validate_manifest(manifest_path(target,'q5'),direct['run_id'])

            return {'metrics':result,'pipeline_run_id':top['run_id'],'scope':'长度、图的存在、公式及交付一致；设计推演由同一 AI 完成，未部署/压测/独立人员审阅'}
        e.check('文档、情景手算与正式默认入口',document)
        e.report.update(requirement_id='Q5.1',production_source_sha256=source_hashes(),review_scope='设计回答与架构图、字数、成本公式和交付一致；不是时延/吞吐实测')
        e.report['artifact_sha256']={str(p.relative_to(ROOT)):sha256(p) for p in [SOURCE,ROOT/'q5_system_design/design_metrics.json']}
        e.save()
    return 0 if e.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
