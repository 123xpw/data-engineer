"""Q4 R1：全量无网络分流、手造反例和变异实验；明确排除真实模型/账单/人工准确率。"""
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_manifest import digest, manifest_path, source_hashes, validate_manifest
from scripts.verification_support import EvidenceRun, require


def execute(args, cwd=ROOT, expected=0, env=None):
    result = subprocess.run([sys.executable, *map(str, args)], cwd=cwd, capture_output=True, text=True, timeout=90, env=env)
    require(result.returncode == expected, f'命令退出码 {result.returncode}，预期 {expected}；{result.stderr[-1500:]}')
    return result


def mutations():
    source = (ROOT/'q4_llm_extraction/extract_reviews.py').read_text()
    variants = [
        ('移除逐条引文校验', "quote not in wanted[sid]['message']", 'False', 'test_schema_counterexamples'),
        ('预算占用恒为零', "return sum((Decimal(e.get('usage_cost_upper_bound_usd', e['reserved_usd'])) for e in self.data['entries'].values()), Decimal(0))", 'return Decimal(0)', 'test_cumulative_budget_includes_prior_uncertain_request'),
        ('禁止行级成功恢复', 'return recovered, blocked', 'return {}, blocked', 'test_expanding_batch_does_not_recharge_or_overwrite_duplicate_review_ids'),
        ('丢失中断请求行标识', "'row_keys': row_keys", "'row_keys': {}", 'test_expanding_after_uncertain_call_never_resends_same_rows'),
    ]
    evidence = []
    with tempfile.TemporaryDirectory(prefix='gekko-q4-mutants-') as folder:
        base = Path(folder); (base/'tests').mkdir(); (base/'tests/__init__.py').touch()
        shutil.copyfile(ROOT/'tests/test_q4.py', base/'tests/test_q4.py')
        shutil.copyfile(ROOT/'artifact_manifest.py', base/'artifact_manifest.py')
        shutil.copytree(ROOT/'q4_llm_extraction', base/'q4_llm_extraction',
                        ignore=shutil.ignore_patterns('__pycache__','extracted_issues.json','annotation_blind.json','run_metrics.json','q4_manifest.json','cost_report.md'))
        execute(['-m','unittest','tests.test_q4'],cwd=base)
        for name, before, after, target in variants:
            require(source.count(before) == 1, '变异目标已变化，须重新审查实验')
            (base/'q4_llm_extraction/extract_reviews.py').write_text(source.replace(before, after))
            shutil.rmtree(base/'q4_llm_extraction/__pycache__', ignore_errors=True)
            result = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_q4.Q4Cases.'+target], cwd=base,
                                    capture_output=True, text=True, timeout=20)
            require(result.returncode != 0 and ('FAIL:' in result.stderr or 'ERROR:' in result.stderr), name+' 没有被预设测试检出')
            # 失败必须来自所选反例，而不能是 import 错误。
            require('FAIL: '+target in result.stderr, name+' 只是运行错误，没有捕获指定性质')
            evidence.append({'mutation':name,'target_test':target,'exit_code':result.returncode,'failure_tail':result.stderr[-1500:]})
    return {'mutations':evidence,'scope':'四个定向局部故障能被检出，不代表所有错误或未知语义均能检出'}


def real_plan():
    output = ROOT/'.venv/q4-engineering-output'
    report = ROOT/'.venv/q4-plan-execution.json'
    env = os.environ.copy(); env.update(Q4_LIVE='1', Q4_CONFIG='/does-not-exist/force-plan-must-ignore')
    with tempfile.TemporaryDirectory(prefix='gekko-q4-cli-') as folder:
        execute([ROOT/'run_all.py','--stage','q4','--q4-plan','--q4-output-dir',output,'--report',report], cwd=folder, expected=2, env=env)
    top = json.loads(report.read_text()); require(top['results'][0]['status']=='partial' and top['exit_code']==2,'分流被误报完成')
    record = validate_manifest(manifest_path(output,'q4'), top['run_id'], allow_partial=True)
    require(record['status']=='partial','清单没有标注未完成')
    try:validate_manifest(manifest_path(output,'q4'),top['run_id'])
    except ValueError:pass
    else:raise AssertionError('普通成功消费者接受了未完成 Q4')
    actual = json.loads((output/'extracted_issues.json').read_text()); metrics=json.loads((output/'run_metrics.json').read_text())
    expected=[]; total=0; routes=Counter(); raw_ids=Counter()
    # 独立解析器和冻结白名单；不调用生产 read_reviews/route 来生成预期。
    generic={'ruim','muito ruim','péssimo','pessimo','bom','muito bom','ótimo','otimo'}
    with (ROOT/'data/olist/olist_order_reviews_dataset.csv').open(newline='',encoding='utf-8') as stream:
        for source_row,row in enumerate(csv.DictReader(stream),1):
            total+=1
            if int(row['review_score'])>3:continue
            message=row['review_comment_message']; branch='no_text' if not message.strip() else 'generic' if message.strip().lower().strip(' .!?,;:') in generic else 'llm'
            routes[branch]+=1;raw_ids[row['review_id']]+=1
            expected.append((source_row,row['review_id'],row['order_id'],branch))
    require(total==99224 and len(expected)==22754,'冻结输入全量行数变化')
    require([(r['source_row'],r['review_id'],r['order_id'],r['route']) for r in actual]==expected,'来源行、顺序或分流与独立 CSV 不同')
    require(dict(routes)=={'no_text':8309,'llm':14294,'generic':151},'固定路由口径变化，须解释并重新验收')
    require(sum(v-1 for v in raw_ids.values())==261,'重复评价来源分母变化')
    require(metrics['routes']==dict(routes) and metrics['api_entries_campaign']==0 and not metrics['live'],'无网络路径出现真实调用声明')
    require(all(r['status']=='pending' and all(r[k] is None for k in ['issues','sentiment_score','confidence','actionable_for_seller']) for r in actual if r['route']=='llm'),'待模型行被填造结论')
    sample=json.loads((output/'annotation_blind.json').read_text())
    require(len(sample['rows'])==30 and all(r['labels'] is None and r['prediction_audit'] is None for r in sample['rows']),'盲标样本非空或已由 AI 填标签')
    scores = {sid: hashlib.sha256(f'gekko-q4-blind-v1:{sid}'.encode()).hexdigest() for sid,_,_,branch in expected if branch!='no_text'}
    require([r['source_row'] for r in sample['rows']]==sorted(scores,key=scores.get)[:30],'盲标样本来源不一致')
    rejected=subprocess.run([sys.executable,str(ROOT/'q4_llm_extraction/evaluate_annotations.py'),'--labels',str(output/'annotation_blind.json')],cwd=ROOT,capture_output=True,text=True,timeout=30)
    require(rejected.returncode!=0 and '拒绝报告准确率' in rejected.stderr,'空人工标注竟被当作通过')
    body=''.join((ROOT/'q4_llm_extraction/pipeline_design.md').read_text().splitlines()[2:]);count=len(''.join(body.split()))
    require(300<=count<=500,'Q4 设计文档字数超出 300..500')
    return {'input_rows':total,'low_score_rows':len(expected),'routes':dict(routes),'duplicate_review_id_extra_rows':261,
            'pipeline_run_id':top['run_id'],'pipeline_design_nonwhitespace_chars':count,'blind_sample_source_rows':[r['source_row'] for r in sample['rows']],
            'actual_external_api_calls':0,'human_accuracy':None,'scope':'全量路由与来源一致、部分产物协议；没有真实模型/账单/人工准确率证据'}


def main():
    with EvidenceRun(ROOT/'reports/q4','engineering') as evidence:
        evidence.check('预设反例、计费手算、恢复与墙钟进程终止',lambda:{'exit_code':execute(['-m','unittest','tests.test_q4','tests.test_q4_cost_report','tests.test_q4_repair','tests.test_artifact_manifest','-v']).returncode,'scope':'合成夹具与真实本地进程，无外部调用'})
        evidence.check('定向变异必须由指定反例检出',mutations)
        evidence.check('全量冻结输入、独立分流、部分状态与空标注拒绝',real_plan)
        evidence.report.update(requirement_id='Q4.R1',production_source_sha256=source_hashes(),
                              review_scope='仅无凭据工程闭环；R2 真实服务/账单和 R3 真人语义评估仍待完成',
                              remaining=['真实小样本与全量调用','实际用量/账单核对及时间预算','真人盲标与语义错误分析'])
        paths=['.venv/q4-engineering-output/'+name for name in ['extracted_issues.json','run_metrics.json','annotation_blind.json','cost_report.md']]
        paths+=['q4_llm_extraction/pipeline_design.md','q4_llm_extraction/accuracy_evaluation.md']
        evidence.report['artifact_sha256']={p:digest(ROOT/p) for p in paths if (ROOT/p).is_file()};evidence.save()
    return 0 if evidence.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
