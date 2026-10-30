"""已计费批次逐行挽救的对照；不允许用另一次生成覆盖原始响应。"""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from tests.test_q4 import ROW,CONFIG,content,response
from q4_llm_extraction import extract_reviews as q
from scripts.repair_q4 import salvage,repair_batch


class RepairCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.ledger=q.Ledger(Path(self.temp.name))

    def test_salvage_preserves_valid_rows_and_original_failed_response(self):
        rows=[ROW,{**ROW,'source_row':8}];entry=self.ledger.reserve('bad-fixture',CONFIG,row_keys={str(r['source_row']):q.row_key(r,CONFIG) for r in rows})
        raw=response();items=content()['results'];second=deepcopy(items[0]);second['source_row']=8;second['issues'][0]['evidence_quote']='invented'
        raw['choices'][0]['message']['content']=json.dumps({'results':items+[second]})
        self.ledger.receipt(entry,raw);entry.update(status='invalid',usage_cost_upper_bound_usd='0.00025');self.ledger.save()
        self.assertEqual(salvage(rows,CONFIG,self.ledger),1);self.assertEqual(entry['status'],'partial')
        receipt=q.strict_json((self.ledger.path.parent/'receipts'/entry['receipt_file']).read_text())
        self.assertEqual(receipt['raw_response'],raw);self.assertEqual(len(receipt['content']['results']),1)
        values,blocked=q.recover_rows(rows,CONFIG,self.ledger);self.assertEqual(set(values),{7});self.assertEqual(blocked,{8})
        self.assertEqual(salvage(rows,CONFIG,self.ledger),0);self.assertEqual(self.ledger.occupied(),Decimal('0.00025'))

    def test_explicit_repair_request_once_with_fee_retained(self):
        fake=Mock(return_value=response())
        with patch.object(q,'http_transport',fake):
            first=repair_batch([ROW],CONFIG,'fixture',self.ledger,time.monotonic()+5)
            again=repair_batch([ROW],CONFIG,'fixture',self.ledger,time.monotonic()+5)
        self.assertEqual((first,again),('api','already_attempted'));self.assertEqual(fake.call_count,1)
        self.assertEqual(self.ledger.occupied(),Decimal('0.00025'))

    def test_formal_pipeline_salvages_then_repairs_without_manual_command(self):
        rows=[ROW,{**ROW,'source_row':8}];config_path=self.ledger.path.parent/'config.json';config_path.write_text(json.dumps(CONFIG));calls=[]
        def fake(c,key,payload,timeout):
            value=response();value['id']='fixture-'+str(len(calls));calls.append(payload)
            if len(calls)==1:
                item=deepcopy(content()['results'][0]);item['source_row']=8;item['issues'][0]['evidence_quote']='invented'
                result={'results':content()['results']+[item]}
            else:
                item=content()['results'][0];item['source_row']=8;result={'results':[item]}
            value['choices'][0]['message']['content']=json.dumps(result);return value
        with patch.object(q,'read_reviews',return_value=(rows,{'sha256':'fixture'})):
            result=q.run_pipeline('fixture',self.ledger.path.parent/'out',config_path=config_path,api_key='fixture',live=True,state_dir=self.ledger.path.parent,transport=fake)
        self.assertEqual(result['stage_completion'],'passed');self.assertEqual(len(calls),2)
        self.assertEqual(result['metrics']['repair_summary']['eligible_repair_rows'],1)
        self.assertEqual(Decimal(result['metrics']['budget_occupied_usd']),Decimal('0.0005'))

    def test_failed_repair_is_pending_and_never_silently_looped(self):
        config_path=self.ledger.path.parent/'config.json';config_path.write_text(json.dumps(CONFIG));calls=[]
        def fake(*args):
            value=response();item=content();item['results'][0]['issues'][0]['evidence_quote']='invented';value['choices'][0]['message']['content']=json.dumps(item);calls.append(1);return value
        with patch.object(q,'read_reviews',return_value=([ROW],{'sha256':'fixture'})):
            first=q.run_pipeline('fixture',self.ledger.path.parent/'out',config_path=config_path,api_key='fixture',live=True,state_dir=self.ledger.path.parent,transport=fake)
            again=q.run_pipeline('fixture',self.ledger.path.parent/'out',config_path=config_path,api_key='fixture',live=True,state_dir=self.ledger.path.parent,transport=fake)
        self.assertEqual(first['stage_completion'],'partial');self.assertEqual(again['stage_completion'],'partial');self.assertEqual(len(calls),3)

    def test_single_isolation_contains_only_the_failed_review(self):
        config_path=self.ledger.path.parent/'config.json';config_path.write_text(json.dumps(CONFIG));calls=[]
        def fake(c,key,payload,timeout):
            calls.append(payload);value=response();item=content()
            if len(calls)<3:item['results'][0]['issues'][0]['evidence_quote']='invented from another row'
            else:
                self.assertEqual(json.loads(payload['messages'][1]['content'].split('\n',1)[1]),[{'source_row':7,'message':ROW['message']}])
            value['choices'][0]['message']['content']=json.dumps(item);return value
        with patch.object(q,'read_reviews',return_value=([ROW],{'sha256':'fixture'})):
            result=q.run_pipeline('fixture',self.ledger.path.parent/'out',config_path=config_path,api_key='fixture',live=True,state_dir=self.ledger.path.parent,transport=fake)
        self.assertEqual(result['stage_completion'],'passed');self.assertEqual(len(calls),3)


if __name__=='__main__':unittest.main()
