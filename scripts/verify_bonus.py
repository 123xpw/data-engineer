"""加分题事实复算与对话引用校验；不冒称独立业务评审。"""
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from artifact_manifest import digest,source_hashes
from scripts.verification_support import EvidenceRun,require
from scripts.q2_4_reference import read_reference


def main():
    with EvidenceRun(ROOT/'reports/bonus','acceptance') as evidence:
        def conversation():
            messages=json.loads((ROOT/'ai_logs/baseline_conversation.json').read_text())['messages']
            text=(ROOT/'bonus/q6_1_ai_collaboration.md').read_text()
            prompt=next(m for m in messages if m['iteration']==8 and m['role']=='user')
            answer=next(m for m in messages if m['iteration']==8 and m['role']=='assistant')
            for message in (prompt,answer):
                require('```text\n'+'\n'.join(message['content_blocks'])+'\n```' in text,'首条引文与原始可见文字不同')
            turns=[m['iteration'] for m in messages if m['role']=='user' and 8<=m['iteration']<=11]
            require(turns==[8,9,10,11],'Q1.2 用户轮次不一致')
            require('共四个推进请求' in text and '绝非当时的第一条原文' in text,'历史与重做建议未区分')
            return {'relevant_user_iterations':turns,'first_prompt_timestamp':prompt['timestamp'],
                    'verbatim_prompt_and_first_answer_match':True,'scope':'原文引用和轮次一致，复盘判断由 AI 协助，不认证本人已掌握'}
        evidence.check('Q6.1 原文、用户轮次和重写提示区分',conversation)
        def facts():
            text=(ROOT/'bonus/q6_2_business_insights.md').read_text();body=text.split('## 正文\n\n')[1].split('\n## 依据')[0]
            count=len(''.join(body.split()));require(300<=count<=600,'Q6.2 正文字数不符')
            ref=read_reference();old=next(r for r in ref['original'] if r['customer_state']=='SP');new=next(r for r in ref['corrected'] if r['customer_state']=='SP')
            difference=Decimal(old['revenue'])-Decimal(new['price_revenue'])
            require(difference==Decimal('11783.860') and '11,783.860' in body,'SP 纠错金额不符独立 CSV 参考')
            with (ROOT/'data/olist/olist_products_dataset.csv').open(newline='',encoding='utf-8-sig') as stream:
                products=list(csv.DictReader(stream))
            with (ROOT/'data/olist/product_category_name_translation.csv').open(newline='',encoding='utf-8-sig') as stream:
                translations=list(csv.DictReader(stream))
            named={r['product_category_name'] for r in translations if r['product_category_name_english']}
            missing=sum(not r['product_category_name'] for r in products)
            gaps=[r for r in products if r['product_category_name'] and r['product_category_name'] not in named]
            require((len(products),missing,len(gaps),len({r['product_category_name'] for r in gaps}))==(32951,610,13,2),'类别事实不符原始 CSV')
            # 从原始 CSV 重新比较已输出候选的价格；不使用 price_mismatch 布尔列自证。
            import pandas as pd
            returns=pd.read_parquet(ROOT/'q3_etl_pipeline/outputs/returns_log.parquet')
            pairs=[(int(r.source_row),int(r.matched_source_row)) for r in returns.itertuples() if not pd.isna(r.matched_source_row)]
            wanted={i for pair in pairs for i in pair};prices={}
            with (ROOT/'data/online_retail_ii.csv').open(newline='',encoding='utf-8') as stream:
                for number,row in enumerate(csv.DictReader(stream),1):
                    if number in wanted:prices[number]=Decimal(row['Price'])
            mismatch=sum(prices[a]!=prices[b] for a,b in pairs)
            require((len(pairs),mismatch)==(6303,217),'退货候选/原始价格差异不符')
            require(all(token in body for token in ['6,303','217','610','13','623','不是新增收入','假设'] ) or
                    all(token in body for token in ['6,303','217','610','13','623','不是新增收入','如果']),'文中数字或假设界限缺失')
            return {'body_nonwhitespace_chars':count,'sp_price_overcount_raw_units':str(difference),
                    'products':len(products),'missing_category':missing,'named_translation_gap':len(gaps),'potential_classification_coverage':missing+len(gaps),
                    'return_candidates':len(pairs),'raw_price_mismatch_candidates':mismatch,'manual_work_hours_if_5min_each':str(Decimal(mismatch)*5/60),
                    'scope':'事实重新解析/Decimal 复算；收益为情景，未做因果/业务 ROI 认证'}
        evidence.check('Q6.2 逐事实独立复算与字数边界',facts)
        evidence.report['artifact_sha256']={str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'bonus').glob('*.md')}
        evidence.report.update(requirement_id='Q6',production_source_sha256=source_hashes(),review_scope='可见原文引用、业务事实和收益假设范围；非独立人员语义审核');evidence.save()
    return 0 if evidence.report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
