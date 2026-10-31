"""低分评价分流与可恢复的显式计费抽取；无凭据时只交付未完成状态。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import multiprocessing
import os
import re
from pathlib import Path
import sys
import tempfile
import time
import threading
from functools import wraps
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artifact_manifest import atomic_json, digest

PROMPT = Path(__file__).with_name('prompt_template.txt')
CATEGORIES = {'delivery_late', 'wrong_product', 'quality_defect', 'missing_item',
              'seller_communication', 'packaging', 'other'}
SEVERITIES = {'low', 'medium', 'high'}
# 只接受完整短语，不用子串关键词判断具体问题；标点只去除两端。
GENERIC = {'ruim': -0.6, 'muito ruim': -0.8, 'péssimo': -0.9, 'pessimo': -0.9,
           'bom': 0.6, 'muito bom': 0.8, 'ótimo': 0.9, 'otimo': 0.9}


def utc():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_reviews(path, *, verify=True):
    import pandas as pd
    path = Path(path)
    if verify:
        specs = json.loads((ROOT/'data_sources.json').read_text())['datasets']['olist']['files']
        expected = next(s for s in specs if s['target'].endswith('olist_order_reviews_dataset.csv'))
        if digest(path) != expected['sha256']:
            raise ValueError('评价 CSV 摘要与冻结输入不符')
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    scores = pd.to_numeric(frame['review_score'], errors='raise')
    if not scores.isin([1, 2, 3, 4, 5]).all():
        raise ValueError('评价分数不在整数 1..5')
    rows = []
    for index, row in frame.loc[scores <= 3].iterrows():
        if not row['review_id'] or not row['order_id']:
            raise ValueError('评价标识缺失')
        rows.append({'source_row': int(index)+1, 'review_id': row['review_id'],
                     'order_id': row['order_id'], 'message': row['review_comment_message']})
    return rows, {'input_rows': len(frame), 'low_score_rows': len(rows), 'sha256': digest(path)}


def route(message):
    if not message.strip():
        return 'no_text'
    if message.strip().lower().strip(' .!?,;:') in GENERIC:
        return 'generic'
    return 'llm'


def rule_result(row):
    branch = route(row['message'])
    if branch == 'llm':
        return None
    generic = branch == 'generic'
    return {'issues': [], 'sentiment_score': GENERIC[row['message'].strip().lower().strip(' .!?,;:')] if generic else 0.0,
            'actionable_for_seller': False, 'confidence': 0.6 if generic else 0.0}


def finite_number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON 对象重复键')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('JSON 包含非有限常量')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def validate_batch(value, rows):
    if type(value) is not dict or set(value) != {'results'} or type(value['results']) is not list:
        raise ValueError('批结果结构错误')
    wanted = {r['source_row']: r for r in rows}
    result = {}
    keys = {'source_row', 'issues', 'sentiment_score', 'actionable_for_seller', 'confidence'}
    for item in value['results']:
        if type(item) is not dict or set(item) != keys:
            raise ValueError('单条结果字段错误')
        sid = item['source_row']
        if type(sid) is not int or sid not in wanted or sid in result:
            raise ValueError('来源 ID 缺失、错配或重复')
        if not finite_number(item['sentiment_score'], -1, 1) or not finite_number(item['confidence'], 0, 1):
            raise ValueError('分数类型或范围错误')
        if type(item['actionable_for_seller']) is not bool or type(item['issues']) is not list or len(item['issues']) > 6:
            raise ValueError('问题或可行动性类型错误')
        seen = set()
        for issue in item['issues']:
            if type(issue) is not dict or set(issue) != {'category', 'severity', 'evidence_quote', 'evidence_quote_en'}:
                raise ValueError('问题字段错误')
            if issue['category'] not in CATEGORIES or issue['severity'] not in SEVERITIES:
                raise ValueError('问题枚举错误')
            quote, translation = issue['evidence_quote'], issue['evidence_quote_en']
            if type(quote) is not str or not quote.strip() or quote not in wanted[sid]['message']:
                raise ValueError('证据不在对应评价原文')
            if type(translation) is not str or not translation.strip():
                raise ValueError('英文翻译缺失')
            pair = (issue['category'], quote)
            if pair in seen:
                raise ValueError('重复问题')
            seen.add(pair)
        if not item['issues'] and item['actionable_for_seller']:
            raise ValueError('无具体问题却声明可行动')
        result[sid] = {k: v for k, v in item.items() if k != 'source_row'}
    if set(result) != set(wanted):
        raise ValueError('批结果缺少来源行')
    return result


def restore_quote_case(content, rows):
    """只恢复唯一的大小写等价原文片段；原始模型响应另外完整保留。"""
    original={r['source_row']:r['message'] for r in rows};changes=[]
    copied=json.loads(json.dumps(content,ensure_ascii=False,allow_nan=False))
    for item in copied.get('results',[]):
        if type(item) is not dict or type(item.get('source_row')) is not int or item['source_row'] not in original:continue
        text=original[item['source_row']]
        for issue in item.get('issues',[]):
            if type(issue) is not dict:continue
            quote=issue.get('evidence_quote')
            if type(quote) is not str or not quote.strip() or quote in text:continue
            matches=[m for m in re.finditer(re.escape(quote),text,re.IGNORECASE) if m.group().casefold()==quote.casefold()]
            if len(matches)==1:
                match=matches[0];issue['evidence_quote']=match.group()
                changes.append({'source_row':item['source_row'],'model_quote':quote,'original_quote':match.group(),'start':match.start(),'end':match.end()})
    return copied,changes


def local_settings():
    values = {}
    path = ROOT/'.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                if key.strip().startswith('Q4_') or key.strip() in ('OPENAI_API_KEY','DEEPSEEK_API_KEY'):
                    if key.strip() in values:
                        raise ValueError('Q4 配置重复键')
                    values[key.strip()] = value.strip().strip('\"\'')
    values.update({k: v for k, v in os.environ.items() if k.startswith('Q4_') or k in ('OPENAI_API_KEY','DEEPSEEK_API_KEY')})
    return values


def read_config(path):
    config = strict_json(Path(path).read_text())
    required = {'endpoint', 'model', 'input_usd_per_million', 'output_usd_per_million',
                'context_window', 'max_completion_tokens', 'pricing_source', 'pricing_verified_utc', 'batch_size'}
    if not required <= set(config) or set(config)-required-{'provider'}:
        raise ValueError('服务配置字段不完整或含未约定字段')
    parsed = urlsplit(config['endpoint'])
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('端点必须是无凭据、无查询参数的 HTTPS 完整接口 URL')
    if not config['model'] or not str(config['pricing_source']).startswith('https://') or not config['pricing_verified_utc']:
        raise ValueError('模型和已核实的价格来源/时间必须明确配置')
    datetime.fromisoformat(config['pricing_verified_utc'].replace('Z', '+00:00'))
    for key in ('input_usd_per_million', 'output_usd_per_million'):
        value = Decimal(str(config[key]))
        if not value.is_finite() or value <= 0:
            raise ValueError('USD 单价必须是已核实的正有限数')
    for key in ('context_window', 'max_completion_tokens', 'batch_size'):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError('服务上界必须是正整数')
    if config['batch_size'] > 16 or config['max_completion_tokens'] >= config['context_window']:
        raise ValueError('批大小或上下文上界错误')
    if config.get('provider', 'openai_compatible') not in ('openai_compatible','deepseek'):
        raise ValueError('未实现的服务协议')
    if config.get('provider') == 'deepseek' and (parsed.hostname != 'api.deepseek.com' or config['model'] not in ('deepseek-flash','deepseek-v4-pro')):
        raise ValueError('DeepSeek 专用协议端点或模型不符')
    return config


def token_cost(config, input_tokens, output_tokens):
    return (Decimal(input_tokens)*Decimal(str(config['input_usd_per_million'])) +
            Decimal(output_tokens)*Decimal(str(config['output_usd_per_million'])))/Decimal(1_000_000)


def row_key(row, config):
    return fingerprint({'config': {k: v for k, v in config.items() if k != 'batch_size'}, 'prompt_sha256': digest(PROMPT),
                        'source_row': row['source_row'], 'message': row['message']})


def recover_rows(rows, config, ledger):
    """按行恢复，不让试运行长度/批次边界变化引起重复付费。"""
    wanted = {str(row['source_row']): (row_key(row, config), row) for row in rows}
    recovered, blocked = {}, set()
    for entry in ledger.data['entries'].values():
        for sid, signature in entry.get('row_keys', {}).items():
            if sid not in wanted or wanted[sid][0] != signature:
                continue
            if entry['status'] in ('valid','partial'):
                item = next((i for i in ledger.content(entry)['results'] if str(i['source_row']) == sid),None)
                if item is not None:recovered.update(validate_batch({'results': [item]}, [wanted[sid][1]]))
                else:blocked.add(int(sid))
            else:
                blocked.add(int(sid))
    blocked.difference_update(recovered)
    return recovered, blocked


def synchronized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self.lock:return method(self,*args,**kwargs)
    return call


@contextmanager
def exclusive_state(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'campaign.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('已有 Q4 任务使用累计账本，拒绝并发') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Ledger:
    """全任务共用持久账本；未知计费保留预留，不自动重发。"""
    def __init__(self, directory, budget='3', *, run_started_epoch=None):
        self.path = Path(directory)/'ledger.json'
        self.lock = threading.RLock()
        self.budget = Decimal(str(budget))
        self.run_started_epoch = run_started_epoch if run_started_epoch is not None else time.time()
        if not self.budget.is_finite() or not 0 < self.budget <= 3:
            raise ValueError('总预算必须在 0..3 USD 内')
        self.data = strict_json(self.path.read_text()) if self.path.exists() else {'schema_version': 2, 'first_request_epoch': None, 'entries': {}}
        if self.data.get('schema_version') != 2:
            raise ValueError('未知账本版本')

    @synchronized
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(dir=self.path.parent,prefix='.ledger-')
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(json.dumps(self.data,ensure_ascii=False,allow_nan=False,separators=(',',':')))
                stream.flush();os.fsync(stream.fileno())
            os.replace(name,self.path)
        finally:Path(name).unlink(missing_ok=True)
        directory = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def content(self,entry):
        if 'content' in entry:return entry['content']
        return strict_json((self.path.parent/'receipts'/entry['receipt_file']).read_text())['content']

    def receipt(self,entry,response,*,content=None,repairs=None):
        filename=entry['request_key']+'.json'
        atomic_json(self.path.parent/'receipts'/filename,{'raw_response':response,'content':content,'quote_case_repairs':repairs})
        entry['receipt_file']=filename

    @synchronized
    def occupied(self):
        return sum((Decimal(e.get('usage_cost_upper_bound_usd', e['reserved_usd'])) for e in self.data['entries'].values()), Decimal(0))

    @synchronized
    def reserve(self, key, config, *, row_keys):
        amount = token_cost(config, config['context_window'], config['max_completion_tokens'])
        if self.occupied()+amount > self.budget:
            raise RuntimeError('budget_exhausted')
        epoch = time.time()
        first = self.data['first_request_epoch']
        if first is None:
            self.data['first_request_epoch'] = self.run_started_epoch
        entry = {'status': 'reserved', 'reserved_usd': str(amount), 'reserved_utc': utc(), 'config': config, 'row_keys': row_keys,'request_key':key}
        self.data['entries'][key] = entry
        self.save()
        return entry


def http_transport(config, key, payload, timeout):
    """读超时不等于总时限；隔离进程保证慢滴流请求也可终止。"""
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    worker = context.Process(target=_http_worker, args=(child, config, key, payload, timeout))
    worker.start(); child.close()
    try:
        if not parent.poll(timeout):
            raise TimeoutError('请求达到墙钟时限；保留未知计费预留')
        success, value = parent.recv()
        if not success:
            raise RuntimeError('服务请求失败：'+value)
        return value
    finally:
        parent.close()
        if worker.is_alive():
            worker.terminate()
        worker.join(timeout=1)
        if worker.is_alive():
            worker.kill(); worker.join(timeout=1)


def _http_worker(pipe, config, key, payload, timeout):
    import requests
    try:
        # 不重试 POST；禁用重定向，密钥不得转发到其他端点。
        with requests.post(config['endpoint'], headers={'Authorization': 'Bearer '+key},
                           json=payload, timeout=(min(5, timeout), timeout),
                           allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise RuntimeError('非 200')
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 5_000_000:
                    raise ValueError('服务响应超过限制')
            pipe.send((True, strict_json(content.decode('utf-8'))))
    except Exception as exc:
        pipe.send((False, type(exc).__name__))
    finally:
        pipe.close()


def request_batch(rows, config, api_key, ledger, deadline, *, transport=http_transport):
    payload = {'model': config['model'], 'messages': [
        {'role': 'system', 'content': PROMPT.read_text()},
        {'role': 'user', 'content': canonical([{'source_row': r['source_row'], 'message': r['message']} for r in rows])}],
        'response_format': {'type': 'json_object'}, 'max_completion_tokens': config['max_completion_tokens']}
    if config.get('provider') == 'deepseek':
        payload['max_tokens'] = payload.pop('max_completion_tokens')
        payload['thinking'] = {'type':'disabled'}
    key = fingerprint({'config': config, 'payload': payload})
    existing = ledger.data['entries'].get(key)
    if existing:
        if existing['status'] == 'valid':
            return validate_batch(ledger.content(existing), rows), 'cache'
        return {}, 'prior_'+existing['status']
    if ledger.data.get('halted'):
        return {}, 'campaign_halted'
    if time.monotonic() >= deadline:
        return {}, 'deadline'
    # 字节界仅作保守的本地预检；付费预留采用已核实的整个模型上下文上界。
    if len(canonical(payload).encode())+1024+config['max_completion_tokens'] > config['context_window']:
        return {}, 'context_preflight'
    try:
        entry = ledger.reserve(key, config, row_keys={str(r['source_row']): row_key(r, config) for r in rows})
    except RuntimeError as exc:
        return {}, str(exc)
    try:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('deadline')
        response = transport(config, api_key, payload, min(45, remaining))
    except Exception as exc:
        return record_failure(ledger,entry,exc)
    with ledger.lock:
        return settle_response(rows,config,ledger,entry,response)


def record_failure(ledger,entry,exc):
    with ledger.lock:
        entry.update(status='uncertain' if 'usage_cost_upper_bound_usd' not in entry else 'invalid',error_type=type(exc).__name__,finished_utc=utc(),finished_epoch=time.time())
        if isinstance(exc,ValueError):entry['validation_error']=str(exc)
        ledger.save()
        return {},entry['status']


def settle_response(rows,config,ledger,entry,response):
    try:
        # 先保留服务原始响应；后续解析失败也不能被当作免费。
        entry.update(request_id=response.get('id'),finished_epoch=time.time())
        ledger.receipt(entry,response)
        usage = response['usage']
        incoming, outgoing = usage['prompt_tokens'], usage['completion_tokens']
        if type(incoming) is not int or type(outgoing) is not int or incoming < 0 or outgoing < 0:
            raise ValueError('usage 非非负整数')
        entry.update(usage_cost_upper_bound_usd=str(token_cost(config, incoming, outgoing)), usage=usage)
        if incoming > config['context_window'] or outgoing > config['max_completion_tokens']:
            ledger.data['halted'] = True
            raise ValueError('服务 usage 超过已核实上界；停止继续调用')
        if ledger.occupied() > ledger.budget:
            ledger.data['halted'] = True
            raise ValueError('实际使用超预算；停止继续调用')
        if type(usage.get('total_tokens')) is not int or usage['total_tokens'] != incoming+outgoing:
            raise ValueError('usage 总数不一致')
        if not isinstance(response.get('id'), str) or not response['id'].strip():
            raise ValueError('缺少可核对的服务请求 ID')
        choice = response['choices'][0]
        if choice['finish_reason'] != 'stop':
            raise ValueError('模型输出截断或拒绝')
        content = strict_json(choice['message']['content'])
        content,repairs = restore_quote_case(content, rows)
        validated = validate_batch(content, rows)
        entry['quote_case_repairs'] = repairs
        ledger.receipt(entry,response,content=content,repairs=repairs)
        entry.update(status='valid', request_id=response.get('id'), finished_utc=utc())
        ledger.save()
        return validated, 'api'
    except Exception as exc:
        return record_failure(ledger,entry,exc)


def annotation_sample(rows, size=30):
    eligible = [r for r in rows if r['message'].strip()]
    chosen = sorted(eligible, key=lambda r: hashlib.sha256(f"gekko-q4-blind-v1:{r['source_row']}".encode()).hexdigest())[:size]
    return {'schema_version': 1, 'sampling': '固定种子哈希排序，非空低分来源行，不按 review_id 去重',
            'annotator': None, 'annotated_utc': None,
            'rows': [{**r, 'labels': None, 'prediction_audit': None} for r in chosen]}


def dispatch(rows,config,api_key,ledger,deadline,workers,transport):
    batches=[rows[i:i+config['batch_size']] for i in range(0,len(rows),config['batch_size'])]
    predictions={};modes=Counter();reason=None
    reservation=token_cost(config,config['context_window'],config['max_completion_tokens'])
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active={}
        while batches or active:
            while batches and len(active)<workers and reason is None and time.monotonic()<deadline:
                if ledger.occupied()+reservation>ledger.budget:break
                batch=batches.pop(0)
                future=pool.submit(request_batch,batch,config,api_key,ledger,deadline,transport=transport)
                active[future]=batch
            if not active:
                if batches:reason=reason or ('deadline' if time.monotonic()>=deadline else 'budget_exhausted')
                break
            finished,_=wait(active,return_when=FIRST_COMPLETED)
            for future in finished:
                batch=active.pop(future);values,mode=future.result();modes[mode]+=1;predictions.update(values)
                if mode=='budget_exhausted':
                    # 这里只重试尚未发出的预算申请，不重发模型请求。
                    batches.insert(0,batch)
                elif mode not in ('api','cache','invalid'):
                    reason=reason or mode
            if reason is not None:batches=[]
    return predictions,modes,reason


def run_pipeline(input_path, output_dir, *, config_path=None, api_key=None, live=False, limit=None,
                 budget='3', max_seconds=2400, state_dir=None, transport=http_transport,workers=4):
    started = time.monotonic()
    started_epoch = time.time()
    if not 0 < max_seconds <= 2400 or (limit is not None and limit <= 0) or workers not in (1,2,3,4):
        raise ValueError('时限须 <=2400 秒，试运行条数须为正')
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    rows, input_info = read_reviews(input_path)
    config = read_config(config_path) if live and config_path else None
    if live and (config is None or not api_key):
        raise ValueError('真实调用需要显式服务配置及本地 API Key')
    pending = [r for r in rows if route(r['message']) == 'llm']
    predictions, modes = {}, Counter()
    reason = 'not_requested'
    ledger = None
    repair_summary = None
    if live:
        state_dir = Path(state_dir or ROOT/'.venv/q4_state')
        with exclusive_state(state_dir):
            ledger = Ledger(state_dir, budget, run_started_epoch=started_epoch)
            selected = pending[:limit] if limit else pending
            requested = list(selected)
            predictions, blocked = recover_rows(selected, config, ledger)
            modes['cached_rows'] = len(predictions)
            if blocked:
                reason = 'prior_unresolved_request'
            unknown=any(e['status'] in ('reserved','uncertain') for e in ledger.data['entries'].values())
            selected = [] if blocked and unknown else [r for r in selected if r['source_row'] not in predictions and r['source_row'] not in blocked]
            values,observed,stopped=dispatch(selected,config,api_key,ledger,started+max_seconds,workers,transport)
            predictions.update(values);modes.update(observed)
            from q4_llm_extraction.repair import repair_known
            repaired,repair_modes,repair_summary=repair_known(requested,config,api_key,ledger,started+max_seconds,transport)
            predictions.update(repaired);modes.update('repair.'+mode for mode in repair_modes)
            reason=stopped or ('prior_unresolved_request' if repair_summary['unsafe_requests_present'] else 'complete' if len(predictions)==len(pending) else 'sample_limit' if limit else 'validation_pending')
    results = []
    for row in rows:
        branch = route(row['message']); rule = rule_result(row)
        value = rule if rule is not None else predictions.get(row['source_row'])
        results.append({'source_row': row['source_row'], 'review_id': row['review_id'], 'order_id': row['order_id'],
                        'route': branch, 'status': 'no_text' if branch == 'no_text' else 'resolved' if value is not None else 'pending',
                        **(value if value is not None else {'issues': None, 'sentiment_score': None, 'actionable_for_seller': None, 'confidence': None})})
    unresolved = sum(r['status'] == 'pending' for r in results)
    entries = list(ledger.data['entries'].values()) if ledger else []
    charged_rows = sum(len(e.get('row_keys', {})) for e in entries if 'usage_cost_upper_bound_usd' in e)
    metrics = {**input_info, 'output_rows': len(results), 'routes': dict(Counter(r['route'] for r in results)),
               'status_counts': dict(Counter(r['status'] for r in results)), 'unresolved': unresolved,
               'request_modes_this_run': dict(modes), 'stop_reason': reason, 'live': live,
               'cached_model_rows_this_run':modes.get('cached_rows',0),
               'request_events_this_run':{k:v for k,v in modes.items() if k!='cached_rows'},
               'configured_workers':workers,'repair_summary':repair_summary,
               'api_entries_campaign': len(entries), 'usage_cost_upper_bound_usd': str(sum((Decimal(e['usage_cost_upper_bound_usd']) for e in entries if 'usage_cost_upper_bound_usd' in e), Decimal(0))),
               'prompt_tokens_campaign': sum(e.get('usage', {}).get('prompt_tokens', 0) for e in entries),
               'completion_tokens_campaign': sum(e.get('usage', {}).get('completion_tokens', 0) for e in entries),
               'usage_reported_text_rows_campaign': charged_rows,
               'budget_occupied_usd': str(ledger.occupied()) if ledger else '0',
               'uncertain_cost_requests': sum('usage_cost_upper_bound_usd' not in e for e in entries),
               'prompt_sha256': digest(PROMPT), 'seconds': round(time.monotonic()-started, 6),
               'service_config_sha256': digest(config_path) if live else None,
               'actual_billed_cost_usd': None,
               'scope': '逐行分流及调用控制；usage 按配置单价计算，非账单认证；引文校验不认证语义；人工评估另行完成'}
    metrics['average_reported_cost_per_queried_row_usd'] = str(Decimal(metrics['usage_cost_upper_bound_usd'])/charged_rows) if charged_rows else None
    atomic_json(output_dir/'extracted_issues.json', results)
    atomic_json(output_dir/'run_metrics.json', metrics)
    atomic_json(output_dir/'annotation_blind.json', annotation_sample(rows))
    (output_dir/'cost_report.md').write_text('# Q4 成本记录\n\n'+
        f"本次 {'真实服务模式' if live else '无网络分流模式'}；累计请求 {len(entries)}，服务报告用量按配置上界折算 {metrics['usage_cost_upper_bound_usd']} USD，保守占用 {metrics['budget_occupied_usd']} USD，未知计费 {metrics['uncertain_cost_requests']} 次。实际账单费用未核对，为 null。\n\n"+
        f"累计已报告输入 token {metrics['prompt_tokens_campaign']}，输出 token {metrics['completion_tokens_campaign']}；已报告用量的请求覆盖 {charged_rows} 条文本（重付费的语义版本分别计次），单条均费 {metrics['average_reported_cost_per_queried_row_usd']} USD。无请求时均费为 null，不以零代表完成。\n\n"+
        '无网络模式的零请求不代表全量模型免费。用量明细在本地累计账本 .venv/q4_state/ledger.json；不得删账本重置预算。价格需先核实，最终须与实际服务账单核对；未完成前不宣称已独立核实实际美元账单。\n\n'+
        '公开材料仅展示实际模型用量和官方费率计算的费用上界，独立实际账单尚未核验。首次实际处理及缓存阶段的用时见 [运行阶段](../reports/q4/real_execution_milestones.json)，不能把缓存重放秒数当作无缓存模型全量耗时。\n', encoding='utf-8')
    metrics['seconds'] = round(time.monotonic()-started, 6)
    metrics['under_time_limit'] = metrics['seconds'] <= max_seconds
    first = ledger.data['first_request_epoch'] if ledger else None
    last=max((e.get('finished_epoch',first) for e in entries),default=first)
    metrics['campaign_elapsed_seconds'] = round(last-first, 6) if first else None
    metrics['campaign_span_is_execution_time'] = False
    atomic_json(output_dir/'run_metrics.json', metrics)
    return {'stage_completion': 'partial' if unresolved or not metrics['under_time_limit'] else 'passed', 'metrics': metrics}


def configured_key(settings, config_path):
    if settings.get('Q4_API_KEY'):
        return settings['Q4_API_KEY']
    # 通用配置不得把 OpenAI Key 隐式转发给另一家兼容服务。
    if config_path and urlsplit(read_config(config_path)['endpoint']).hostname == 'api.openai.com':
        return settings.get('OPENAI_API_KEY')
    if config_path and urlsplit(read_config(config_path)['endpoint']).hostname == 'api.deepseek.com':
        return settings.get('DEEPSEEK_API_KEY')
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'data/olist/olist_order_reviews_dataset.csv')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent)
    parser.add_argument('--live', action='store_true', help='显式允许真实付费请求；默认不联网')
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('deepseek_config.json'))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--budget', default='3')
    parser.add_argument('--max-seconds', type=float, default=2400)
    parser.add_argument('--workers',type=int,choices=(1,2,3,4),default=4)
    args = parser.parse_args(); settings = local_settings()
    from artifact_manifest import publish
    result = publish('q4', args.output_dir, lambda fresh: run_pipeline(args.input, fresh, config_path=args.config,
                     api_key=configured_key(settings, args.config) if args.live else None, live=args.live,
                     limit=args.limit, budget=args.budget, max_seconds=args.max_seconds,workers=args.workers), inputs=[args.input,*([args.config] if args.live else [])])
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result['stage_completion'] == 'partial' else 0


if __name__ == '__main__':
    raise SystemExit(main())
