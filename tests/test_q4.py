"""手造葡语反例及计费夹具；这些不是人工标注或真实 API 结果。"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from q4_llm_extraction import extract_reviews as q
from q4_llm_extraction.evaluate_annotations import evaluate


ROW = {'source_row': 7, 'review_id': 'same-id', 'order_id': 'order-1', 'message': 'Produto quebrado. Não chegou atrasado.'}
CONFIG = {'endpoint': 'https://example.invalid/v1/chat/completions', 'model': 'test-only',
          'input_usd_per_million': '1', 'output_usd_per_million': '3', 'context_window': 32768,
          'max_completion_tokens': 1024, 'batch_size': 4, 'pricing_source': 'https://example.invalid/pricing',
          'pricing_verified_utc': '2026-10-30T00:00:00+00:00'}


def content():
    return {'results': [{'source_row': 7, 'issues': [{'category': 'quality_defect', 'severity': 'high',
                         'evidence_quote': 'Produto quebrado', 'evidence_quote_en': 'Broken product'}],
                         'sentiment_score': -0.8, 'actionable_for_seller': True, 'confidence': 0.8}]}


def response():
    return {'id': 'fake-request-not-real', 'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content())}}]}


def slow_worker(pipe, *args):
    """真正的隔离进程，模拟永不及时返回的服务；不访问网络。"""
    time.sleep(5)
    pipe.close()


class Q4Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name); self.ledger = q.Ledger(self.path)

    def call(self, transport, **kwargs):
        return q.request_batch([ROW], CONFIG, 'fixture-key-not-secret', self.ledger, time.monotonic()+5, transport=transport, **kwargs)

    def test_routing_does_not_turn_substring_or_negation_into_rules(self):
        self.assertEqual([q.route(x) for x in [' ', 'Ruim!!!', 'muito bom', 'ruim, não chegou', 'Não é ruim', 'a embalagem ruim']],
                         ['no_text', 'generic', 'generic', 'llm', 'llm', 'llm'])
        self.assertEqual(q.rule_result({'message': ' '}), {'issues': [], 'sentiment_score': 0.0, 'actionable_for_seller': False, 'confidence': 0.0})

    def test_schema_counterexamples(self):
        bad = []
        for key, value in [('source_row', True), ('source_row', 8), ('confidence', True), ('confidence', 1.01),
                           ('sentiment_score', float('nan')), ('sentiment_score', '-1'), ('actionable_for_seller', 1)]:
            item = content(); item['results'][0][key] = value; bad.append(item)
        for key, value in [('evidence_quote', 'Outro produto'), ('evidence_quote', ' '), ('evidence_quote_en', ''),
                           ('severity', 'urgent'), ('category', 'refund')]:
            item = content(); item['results'][0]['issues'][0][key] = value; bad.append(item)
        item = content(); item['results'] *= 2; bad.append(item)
        bad.extend([{'results': []}, {'results': [None]}, {'results': [], 'extra': 1}])
        for item in bad:
            with self.subTest(item=item), self.assertRaises((ValueError, TypeError)):
                q.validate_batch(item, [ROW])
        self.assertIn(7, q.validate_batch(content(), [ROW]))

    def test_quote_check_cannot_prove_semantics(self):
        wrong = content(); wrong['results'][0]['issues'][0].update(category='delivery_late', evidence_quote='Não chegou atrasado', evidence_quote_en='It arrived late')
        # 故意保留“合法结构但错误语义”反例：系统不具备否定/翻译正确性的证明。
        self.assertIn(7, q.validate_batch(wrong, [ROW]))

    def test_duplicate_json_keys_nan_rejected(self):
        for text in ['{"results":[],"results":[]}', '{"value":NaN}', '{"value":Infinity}']:
            with self.assertRaises(ValueError):q.strict_json(text)

    def test_hand_cost_and_resume_without_new_call(self):
        self.assertEqual(q.token_cost(CONFIG, 100, 50), Decimal('0.00025'))
        fake = Mock(return_value=response()); values, mode = self.call(fake)
        self.assertEqual(mode, 'api'); self.assertEqual(self.ledger.occupied(), Decimal('0.00025'))
        self.ledger = q.Ledger(self.path)
        self.assertEqual(self.call(fake)[1], 'cache'); self.assertEqual(fake.call_count, 1)

    def test_uncertain_timeout_reserves_and_never_auto_retries(self):
        fake = Mock(side_effect=TimeoutError())
        self.assertEqual(self.call(fake)[1], 'uncertain')
        self.assertEqual(self.ledger.occupied(), Decimal('0.03584'))
        self.ledger = q.Ledger(self.path)
        self.assertEqual(self.call(fake)[1], 'prior_uncertain'); self.assertEqual(fake.call_count, 1)

    def test_reservation_precedes_network_and_interrupt_survives(self):
        def interrupt(*args):
            disk=json.loads(self.ledger.path.read_text())
            self.assertEqual(next(iter(disk['entries'].values()))['status'], 'reserved')
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.call(interrupt)
        self.ledger = q.Ledger(self.path)
        self.assertEqual(self.call(Mock(side_effect=AssertionError('不得重发')))[1], 'prior_reserved')

    def test_missing_usage_is_unknown_not_free(self):
        value = response(); del value['usage']
        self.assertEqual(self.call(Mock(return_value=value))[1], 'uncertain')
        self.assertEqual(self.ledger.occupied(), Decimal('0.03584'))

    def test_deepseek_protocol_and_empty_stop_is_not_success(self):
        config={**CONFIG,'provider':'deepseek','endpoint':'https://api.deepseek.com/chat/completions','model':'deepseek-flash'}
        def fake(c,key,payload,timeout):
            self.assertEqual(payload['max_tokens'],1024)
            self.assertNotIn('max_completion_tokens',payload)
            self.assertEqual(payload['thinking'],{'type':'disabled'})
            value=response();value['choices'][0]['message']['content']='   '
            return value
        values,mode=q.request_batch([ROW],config,'fixture',self.ledger,time.monotonic()+5,transport=fake)
        self.assertEqual((values,mode),({},'invalid'))
        self.assertEqual(self.ledger.occupied(),Decimal('0.00025'))

    def test_deepseek_key_not_forwarded_to_another_provider(self):
        path=self.path/'config.json';path.write_text(json.dumps(CONFIG))
        self.assertIsNone(q.configured_key({'DEEPSEEK_API_KEY':'fixture'},path))
        config={**CONFIG,'provider':'deepseek','endpoint':'https://api.deepseek.com/chat/completions','model':'deepseek-flash'}
        path.write_text(json.dumps(config))
        self.assertEqual(q.configured_key({'DEEPSEEK_API_KEY':'fixture'},path),'fixture')
        path.write_text(json.dumps({**config,'endpoint':'https://example.invalid/chat/completions'}))
        with self.assertRaises(ValueError):q.read_config(path)

    def test_shipped_deepseek_budget_is_peak_upper_bound_not_a_bill(self):
        config=q.read_config(q.ROOT/'q4_llm_extraction/deepseek_config.json')
        self.assertEqual(q.token_cost(config,config['context_window'],config['max_completion_tokens']),Decimal('0.3182592'))
        self.assertEqual(config['provider'],'deepseek')

    def test_known_charge_retained_after_invalid_or_truncated_response(self):
        for reason in ['length', 'content_filter']:
            with self.subTest(reason=reason):
                self.ledger = q.Ledger(self.path/reason)
                value = response(); value['choices'][0]['finish_reason'] = reason
                self.assertEqual(self.call(Mock(return_value=value))[1], 'invalid')
                self.assertEqual(self.ledger.occupied(), Decimal('0.00025'))

    def test_low_budget_no_network(self):
        self.ledger = q.Ledger(self.path, '0.01'); fake = Mock()
        self.assertEqual(self.call(fake)[1], 'budget_exhausted'); fake.assert_not_called()
        for value in ['NaN', '0', '3.01']:
            with self.assertRaises(ValueError):q.Ledger(self.path, value)

    def test_elapsed_campaign_and_single_call_deadline_block_network(self):
        self.ledger.data['first_request_epoch'] = time.time()-2401
        fake = Mock(); self.assertEqual(self.call(fake)[1], 'campaign_deadline'); fake.assert_not_called()
        values, mode=q.request_batch([ROW], CONFIG, 'fixture', self.ledger, time.monotonic()-1, transport=fake)
        self.assertEqual(mode, 'deadline'); fake.assert_not_called()

    def test_cumulative_budget_includes_prior_uncertain_request(self):
        self.ledger=q.Ledger(self.path,'0.05');fake=Mock(side_effect=TimeoutError())
        self.assertEqual(self.call(fake)[1],'uncertain')
        self.ledger=q.Ledger(self.path,'0.05')
        other={**ROW,'source_row':8}
        self.assertEqual(q.request_batch([other],CONFIG,'fixture',self.ledger,time.monotonic()+5,transport=fake)[1],'budget_exhausted')
        self.assertEqual(fake.call_count,1)

    def test_usage_over_verified_bound_persistently_halts_campaign(self):
        value=response();value['usage'].update(prompt_tokens=40000,total_tokens=40050)
        self.assertEqual(self.call(Mock(return_value=value))[1], 'invalid')
        self.ledger=q.Ledger(self.path);other={**ROW,'source_row':8}
        fake=Mock();self.assertEqual(q.request_batch([other],CONFIG,'fixture',self.ledger,time.monotonic()+5,transport=fake)[1],'campaign_halted');fake.assert_not_called()

    def test_lock_excludes_concurrent_campaign(self):
        with q.exclusive_state(self.path):
            with self.assertRaises(RuntimeError):
                with q.exclusive_state(self.path):pass

    def test_changed_prompt_invalidates_cache_without_resetting_cost(self):
        fake=Mock(return_value=response());self.call(fake)
        prompt=self.path/'prompt.txt';prompt.write_text('另一套提示 JSON')
        with patch.object(q,'PROMPT',prompt):self.call(fake)
        self.assertEqual(fake.call_count,2);self.assertEqual(self.ledger.occupied(),Decimal('0.0005'))

    def test_wall_clock_terminates_slow_process(self):
        before=time.monotonic()
        with patch.object(q,'_http_worker',slow_worker), self.assertRaises(TimeoutError):
            q.http_transport(CONFIG,'fixture',{},0.1)
        self.assertLess(time.monotonic()-before,1.5)

    def test_expanding_batch_does_not_recharge_or_overwrite_duplicate_review_ids(self):
        rows=[{**ROW,'source_row':i,'order_id':str(i)} for i in [7,8,9,10]]
        config_path=self.path/'config.json';config_path.write_text(json.dumps(CONFIG))
        called=[]
        def fake(config,key,payload,timeout):
            submitted=json.loads(payload['messages'][1]['content']);called.extend(r['source_row'] for r in submitted)
            value=response();items=[]
            for row in submitted:
                item=content()['results'][0];item['source_row']=row['source_row'];items.append(item)
            value['choices'][0]['message']['content']=json.dumps({'results':items})
            return value
        with patch.object(q,'read_reviews',return_value=(rows,{'sha256':'fixture'})):
            first=q.run_pipeline('fixture',self.path/'out',config_path=config_path,api_key='fixture',live=True,limit=1,state_dir=self.path/'state',transport=fake)
            self.assertEqual(first['stage_completion'],'partial')
            config_path.write_text(json.dumps({**CONFIG,'batch_size':2}))
            full=q.run_pipeline('fixture',self.path/'out',config_path=config_path,api_key='fixture',live=True,state_dir=self.path/'state',transport=fake)
        self.assertEqual(full['stage_completion'],'passed');self.assertEqual(called,[7,8,9,10])
        actual=json.loads((self.path/'out/extracted_issues.json').read_text());self.assertEqual(len(actual),4)
        self.assertEqual({r['review_id'] for r in actual},{'same-id'})

    def test_expanding_after_uncertain_call_never_resends_same_rows(self):
        rows=[ROW,{**ROW,'source_row':8}];config_path=self.path/'config.json';config_path.write_text(json.dumps(CONFIG))
        fake=Mock(side_effect=TimeoutError())
        with patch.object(q,'read_reviews',return_value=(rows,{'sha256':'fixture'})):
            q.run_pipeline('fixture',self.path/'out',config_path=config_path,api_key='fixture',live=True,limit=1,state_dir=self.path/'state',transport=fake)
            second=q.run_pipeline('fixture',self.path/'out',config_path=config_path,api_key='fixture',live=True,state_dir=self.path/'state',transport=fake)
        self.assertEqual(fake.call_count,1);self.assertEqual(second['metrics']['stop_reason'],'prior_unresolved_request')

    def test_annotation_empty_rejected_and_hand_metrics(self):
        rows=[{**ROW,'source_row':i,'review_id':str(i)} for i in range(1,31)]
        sample=q.annotation_sample(rows)
        with self.assertRaises(ValueError):evaluate(sample,[],sample)
        labels=deepcopy(sample);labels.update(annotator='合成夹具，不是真人',annotated_utc='2026-10-30T00:00:00+00:00')
        predictions=[]
        for row in labels['rows']:
            row['labels']={'categories':['quality_defect'],'sentiment':'negative','actionable_for_seller':True,'note':'手算夹具'}
            row['prediction_audit']={'evidence_supported':True,'translation_faithful':True,'severity_reasonable':True}
            predictions.append({**row,**q.validate_batch(content(),[ROW])[7],'status':'resolved'})
        # 每条人工一个类别，预测同时加一个错误类别：TP30/FP30/FN0 => P=.5,R=1,F1=2/3。
        for pred in predictions:pred['issues']=deepcopy(pred['issues'])+[{'category':'packaging','severity':'medium','evidence_quote':'Não chegou atrasado','evidence_quote_en':'It did not arrive late'}]
        result=evaluate(labels,predictions,sample)
        self.assertEqual((result['tp'],result['fp'],result['fn']),(30,30,0))
        self.assertEqual(result['micro_precision'],0.5);self.assertEqual(result['micro_f1'],2/3)


if __name__=='__main__':unittest.main()
