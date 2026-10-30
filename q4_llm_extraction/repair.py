"""逐行挽救已付费响应；仅对明确计费、仍无有效结果的行做一次显式格式修复。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from q4_llm_extraction import extract_reviews as q


def salvage(rows,config,ledger):
    index={r['source_row']:r for r in rows};saved=0
    for entry in list(ledger.data['entries'].values()):
        if entry['status'] not in ('invalid','partial') or 'usage_cost_upper_bound_usd' not in entry or 'receipt_file' not in entry:continue
        originals=[index[int(sid)] for sid,signature in entry['row_keys'].items()
                   if int(sid) in index and q.row_key(index[int(sid)],config)==signature]
        if len(originals)!=len(entry['row_keys']):continue
        receipt=q.strict_json((ledger.path.parent/'receipts'/entry['receipt_file']).read_text());response=receipt['raw_response']
        try:
            content=q.strict_json(response['choices'][0]['message']['content'])
            items=content['results'];ids=[r['source_row'] for r in items]
            if any(type(i) is not int for i in ids) or len(ids)!=len(set(ids)) or set(ids)!={r['source_row'] for r in originals}:continue
        except (ValueError,KeyError,TypeError):continue
        before={r['source_row'] for r in (receipt.get('content') or {}).get('results',[])}
        accepted=[];repairs=[]
        for item in items:
            row=index[item['source_row']]
            try:
                fixed,changes=q.restore_quote_case({'results':[item]},[row]);q.validate_batch(fixed,[row])
            except (ValueError,TypeError,KeyError):continue
            accepted.extend(fixed['results']);repairs.extend(changes)
        if not accepted:continue
        q_content={'results':accepted}
        ledger.receipt(entry,response,content=q_content,repairs=repairs)
        entry.update(status='valid' if len(accepted)==len(originals) else 'partial',salvage_valid_source_rows=[r['source_row'] for r in accepted])
        ledger.save();saved+=len({r['source_row'] for r in accepted}-before)
    return saved


def repair_batch(rows,config,key,ledger,deadline,transport=None,stage='batch'):
    if stage not in ('batch','single') or (stage=='single' and len(rows)!=1):raise ValueError('修复级别/行数不符')
    payload={'model':config['model'],'messages':[{'role':'system','content':q.PROMPT.read_text()},
             {'role':'user','content':'以下行上次未通过逐字引文或 JSON 校验。这是一次显式修复生成，不要翻译/改写葡语证据，不要增加未提及的事实；没有具体问题则 issues=[] 且 actionable_for_seller=false。逐字复制原 message 中的片段，保留拼写、重音和空格；例如原文 ate 不得写成 até，原文 O 不得写成 a。不要补全被截断的句子；不确定时降低 confidence。只输出约定 JSON。\n'+q.canonical([{'source_row':r['source_row'],'message':r['message']} for r in rows])}],
             'response_format':{'type':'json_object'},'max_completion_tokens':config['max_completion_tokens']}
    if config.get('provider')=='deepseek':
        payload['max_tokens']=payload.pop('max_completion_tokens');payload['thinking']={'type':'disabled'}
    if time.monotonic()>=deadline:return 'deadline'
    request_key=q.fingerprint({'repair_v1':True,'stage':stage,'config':config,'payload':payload})
    if request_key in ledger.data['entries']:return 'already_attempted'
    with ledger.lock:
        try:entry=ledger.reserve(request_key,config,row_keys={str(r['source_row']):q.row_key(r,config) for r in rows})
        except RuntimeError:return 'budget_exhausted'
        entry['explicit_repair']=True;entry['repair_stage']=stage;entry['payload_sha256']=q.fingerprint(payload);ledger.save()
    try:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError()
        response=(transport or q.http_transport)(config,key,payload,min(45,remaining))
    except Exception as exc:return q.record_failure(ledger,entry,exc)[1]
    with ledger.lock:return q.settle_response(rows,config,ledger,entry,response)[1]


def repair_known(rows,config,key,ledger,deadline,transport=None):
    saved=salvage(rows,config,ledger);values,blocked=q.recover_rows(rows,config,ledger)
    attempted=set();unsafe=set()
    for entry in ledger.data['entries'].values():
        for sid,signature in entry.get('row_keys',{}).items():
            if entry.get('explicit_repair'):attempted.add((int(sid),signature))
            if entry['status'] in ('reserved','uncertain'):unsafe.add((int(sid),signature))
    selected=[r for r in rows if r['source_row'] in blocked and (r['source_row'],q.row_key(r,config)) not in attempted|unsafe]
    modes=[]
    if not unsafe:
        batches=[selected[i:i+4] for i in range(0,len(selected),4)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            for i in range(0,len(batches),2):
                if time.monotonic()>=deadline:break
                futures=[pool.submit(repair_batch,b,config,key,ledger,deadline,transport) for b in batches[i:i+2]]
                observed=[f.result() for f in futures];modes.extend(observed)
                if any(m in ('uncertain','budget_exhausted','deadline') for m in observed):break
        salvage(rows,config,ledger);values,blocked=q.recover_rows(rows,config,ledger)
        # 批修复仍可能串用同批其他评价的引文，最后隔离为单条；每行至多一次。
        batch_attempts=set();single_attempts=set()
        for entry in ledger.data['entries'].values():
            if not entry.get('explicit_repair'):continue
            for sid,signature in entry.get('row_keys',{}).items():
                (single_attempts if entry.get('repair_stage')=='single' else batch_attempts).add((int(sid),signature))
        isolated=[r for r in rows if r['source_row'] in blocked and (r['source_row'],q.row_key(r,config)) in batch_attempts-single_attempts]
        if not any(e['status'] in ('reserved','uncertain') for e in ledger.data['entries'].values()):
            with ThreadPoolExecutor(max_workers=2) as pool:
                for i in range(0,len(isolated),2):
                    if time.monotonic()>=deadline:break
                    futures=[pool.submit(repair_batch,[r],config,key,ledger,deadline,transport,'single') for r in isolated[i:i+2]]
                    observed=[f.result() for f in futures];modes.extend('single.'+m for m in observed)
                    if any(m in ('uncertain','budget_exhausted','deadline') for m in observed):break
            salvage(rows,config,ledger);values,blocked=q.recover_rows(rows,config,ledger)
    return values,modes,{'newly_salvaged_valid_rows':saved,'eligible_repair_rows':len(selected),'remaining_blocked_rows':len(blocked),'unsafe_requests_present':bool(unsafe)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    config_path=ROOT/'q4_llm_extraction/deepseek_config.json';config=q.read_config(config_path)
    rows,_=q.read_reviews(ROOT/'data/olist/olist_order_reviews_dataset.csv');rows=[r for r in rows if q.route(r['message'])=='llm']
    with q.exclusive_state(ROOT/'.venv/q4_state'):
        ledger=q.Ledger(ROOT/'.venv/q4_state','3');saved=salvage(rows,config,ledger);values,blocked=q.recover_rows(rows,config,ledger)
        attempted=set();unsafe=set()
        for entry in ledger.data['entries'].values():
            for sid,signature in entry.get('row_keys',{}).items():
                if entry.get('explicit_repair'):attempted.add((int(sid),signature))
                if entry['status'] in ('reserved','uncertain'):unsafe.add((int(sid),signature))
        selected=[r for r in rows if r['source_row'] in blocked and (r['source_row'],q.row_key(r,config)) not in attempted|unsafe]
        modes=[]
        if args.live:
            key=q.configured_key(q.local_settings(),config_path)
            if not key:raise ValueError('缺少服务密钥')
            # 同一账本最坏上下文预留限制实际并行数；最多两路，每行最多一次修复生成。
            batches=[selected[i:i+4] for i in range(0,len(selected),4)];deadline=time.monotonic()+2400
            with ThreadPoolExecutor(max_workers=2) as pool:
                for i in range(0,len(batches),2):
                    futures=[pool.submit(repair_batch,b,config,key,ledger,deadline) for b in batches[i:i+2]]
                    modes.extend(f.result() for f in futures)
                    if any(m in ('uncertain','budget_exhausted') for m in modes[-2:]):break
            salvage(rows,config,ledger);values,blocked=q.recover_rows(rows,config,ledger)
        print(json.dumps({'salvaged_valid_rows':saved,'current_valid_model_rows':len(values),'blocked_rows':len(blocked),
                          'eligible_known_invalid_rows':len(selected),'repair_modes':modes,'budget_occupied_usd':str(ledger.occupied()),
                          'scope':'挽救和修复均不修改原始服务响应，不重发未知计费；当前没有有效响应的行继续 pending'},ensure_ascii=False))


if __name__=='__main__':main()
