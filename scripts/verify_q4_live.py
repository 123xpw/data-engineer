"""真实 Q4 产物/用量/逐行来源核验；通过不等于真人准确率或独立账单认证。"""
import argparse
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import digest,manifest_path,source_hashes,validate_manifest
from q4_llm_extraction.extract_reviews import exclusive_state,read_config,strict_json,token_cost
from scripts.verification_support import EvidenceRun,require


def key_for(row,config,prompt_sha):
    value={'config':{k:v for k,v in config.items() if k!='batch_size'},'prompt_sha256':prompt_sha,
           'source_row':row['source_row'],'message':row['review_comment_message']}
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',type=Path,default=ROOT/'.venv/q4-live-full');args=parser.parse_args()
    with EvidenceRun(ROOT/'reports/q4','processing') as evidence,exclusive_state(ROOT/'.venv/q4_state'):
        state=ROOT/'.venv/q4_state';ledger=strict_json((state/'ledger.json').read_text())
        output=args.output_dir.resolve();config=read_config(ROOT/'q4_llm_extraction/deepseek_config.json');prompt=digest(ROOT/'q4_llm_extraction/prompt_template.txt')
        require(output.is_relative_to(ROOT),'证据产物必须在当前项目目录内')
        def coverage():
            manifest=strict_json(manifest_path(output,'q4').read_text());validate_manifest(manifest_path(output,'q4'),manifest['run_id'])
            metrics=strict_json((output/'run_metrics.json').read_text());actual=strict_json((output/'extracted_issues.json').read_text())
            source=[]
            with (ROOT/'data/olist/olist_order_reviews_dataset.csv').open(newline='',encoding='utf-8-sig') as stream:
                for number,row in enumerate(csv.DictReader(stream),1):
                    if int(row['review_score'])<=3:source.append({**row,'source_row':number})
            require(len(source)==len(actual)==22754,'低分来源覆盖缺失')
            allowed={'delivery_late','wrong_product','quality_defect','missing_item','seller_communication','packaging','other'}
            statuses=Counter();unverified=[];by_source={r['source_row']:r for r in source}
            for row,result in zip(source,actual):
                require(all(row[k]==result[k] for k in ('source_row','review_id','order_id')),'来源顺序或标识错配')
                statuses[result['status']]+=1
                require(result['status'] in ('no_text','resolved'),'仍有待处理结果')
                require(isinstance(result['issues'],list),'问题列表不是数组')
                require(type(result['actionable_for_seller']) is bool,'可行动性不是布尔值')
                for field,low,high in [('sentiment_score',-1,1),('confidence',0,1)]:
                    value=result[field];require(type(value) in (int,float) and math.isfinite(value) and low<=value<=high,'数值类型/范围错误')
                if result['status']=='no_text':require(not row['review_comment_message'].strip() and result['confidence']==0,'无文本状态错误')
                for issue in result['issues']:
                    require(issue['category'] in allowed and issue['severity'] in {'low','medium','high'},'问题枚举错误')
                    quote=issue['evidence_quote'];require(type(quote) is str and quote.strip() and quote in row['review_comment_message'],'最终引文不在原始对应评价')
                    require(type(issue['evidence_quote_en']) is str and issue['evidence_quote_en'].strip(),'译文缺失')
            require(metrics['live'] is True and metrics['unresolved']==0 and metrics['under_time_limit'] and metrics['seconds']<=2400,'真实执行范围/时长未通过')
            # 将当前 LLM 行逐字段绑定到保存的响应，不用产物自填的 resolved 状态自证。
            witnessed={};receipts=0;repair_count=0;case_changes=0;request_ids=[];total=Decimal(0)
            for entry in ledger['entries'].values():
                require(entry['status'] not in ('reserved','uncertain'),'存在未结算请求')
                require('usage_cost_upper_bound_usd' in entry and 'usage' in entry,'请求没有用量费用证据')
                usage=entry['usage'];incoming,outgoing=usage['prompt_tokens'],usage['completion_tokens']
                require(type(incoming) is int and type(outgoing) is int and incoming>=0 and outgoing>=0 and usage['total_tokens']==incoming+outgoing,'服务用量错误')
                cost=token_cost(entry['config'],incoming,outgoing);require(cost==Decimal(entry['usage_cost_upper_bound_usd']),'费用折算不符实际记录用量')
                total+=cost
                if 'receipt_file' in entry:
                    path=state/'receipts'/entry['receipt_file'];receipt=strict_json(path.read_text());raw=receipt['raw_response'];normalized=receipt.get('content')
                else:
                    raw=entry['response'];normalized=entry.get('content')
                require(raw['usage']==usage and isinstance(raw.get('id'),str),'原始回执缺失或用量被改写')
                request_ids.append(raw['id']);receipts+=1;repair_count+=bool(entry.get('explicit_repair'))
                case_changes+=len((receipt.get('quote_case_repairs') or []) if 'receipt_file' in entry else entry.get('quote_case_repairs',[]))
                require(raw.get('model')==entry['config']['model'],'回执模型与配置不符')
                if entry['status'] not in ('valid','partial') or not normalized:continue
                raw_items=strict_json(raw['choices'][0]['message']['content'])['results'];raw_index={r['source_row']:r for r in raw_items}
                for item in normalized['results']:
                    sid=item['source_row']
                    if sid not in by_source or entry['row_keys'].get(str(sid))!=key_for(by_source[sid],config,prompt):continue
                    original=raw_index[sid]
                    require({k:v for k,v in item.items() if k!='issues'}=={k:v for k,v in original.items() if k!='issues'},'响应非引文字段被修改')
                    require(len(item['issues'])==len(original['issues']),'响应问题被无记录增删')
                    for before,after in zip(original['issues'],item['issues']):
                        require({k:v for k,v in before.items() if k!='evidence_quote'}=={k:v for k,v in after.items() if k!='evidence_quote'},'问题非引文字段被修改')
                        require(before['evidence_quote'].casefold()==after['evidence_quote'].casefold(),'引文修复不只是大小写')
                    witnessed[sid]={k:v for k,v in item.items() if k!='source_row'}
            require(len(request_ids)==len(set(request_ids)),'服务请求 ID 重复')
            require(total<=3 and total==Decimal(metrics['usage_cost_upper_bound_usd']),'累计费用不符或超过总预算')
            llm=[r for r in actual if r['route']=='llm']
            require(len(llm)==14294,'模型行分母变化')
            for result in llm:
                require(result['source_row'] in witnessed,'模型结论缺少本版本响应')
                require({k:result[k] for k in ['issues','sentiment_score','actionable_for_seller','confidence']}==witnessed[result['source_row']],'结果与保存响应不同')
            evidence.report['request_ids']=request_ids
            return {'pipeline_run_id':manifest['run_id'],'rows':len(source),'status_counts':dict(statuses),'llm_rows_with_receipts':len(llm),
                    'api_requests_including_failed_versions':receipts,'explicit_repair_requests':repair_count,'case_repairs':case_changes,
                    'cumulative_usage_cost_upper_bound_usd':str(total),'pipeline_seconds':metrics['seconds'],
                    'actual_billed_cost_usd':None,'human_accuracy':None,
                    'earlier_real_execution_stages':'reports/q4/real_execution_milestones.json','fresh_uncached_full_run_certified':False,
                    'scope':'来源/结构/逐字证据/回执用量和时长；原始响应是客户端保存证据，不是服务商签章账单或真人语义认证'}
        evidence.check('真实全量、逐行证据、原始回执与累计预算时长',coverage)
        evidence.report.update(requirement_id='Q4.PROCESSING',production_source_sha256=source_hashes(),review_scope='真实模型处理闭环；不含真人标签和独立账单核对')
        evidence.report['artifact_sha256']={str((output/name).relative_to(ROOT)):digest(output/name) for name in ['extracted_issues.json','run_metrics.json','annotation_blind.json','cost_report.md'] if (output/name).is_file()};evidence.save()
    return 0 if evidence.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
