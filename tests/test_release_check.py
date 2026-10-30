"""用缺项、过期证据挑战放行器；不以全绿计数替代需求覆盖。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import release_check as gate


class ReleaseTests(unittest.TestCase):
    def test_all_green_checks_without_one_required_check_are_rejected(self):
        report={'status':'passed','source_sha256':{},'checks':[{'name':name,'passed':True} for name in sorted(gate.REGRESSION_CHECKS)[:-1]]}
        with self.assertRaisesRegex(AssertionError,'关键检查缺失'):
            gate.inspect_regression(report,{})

    def test_old_source_is_rejected_even_when_every_check_passes(self):
        report={'status':'passed','source_sha256':{'old':'hash'},'checks':[{'name':name,'passed':True} for name in gate.REGRESSION_CHECKS]}
        with self.assertRaisesRegex(AssertionError,'源码已过期'):
            gate.inspect_regression(report,{'new':'hash'})

    def test_complete_claim_without_evidence_remains_pending(self):
        rows=[{'id':key,'status':'verified','reason':'人工全绿声明，没有证据'} for key in gate.REQUIRED_PENDING]
        self.assertEqual({r['id'] for r in gate.pending_items(rows)},gate.REQUIRED_PENDING)
        with self.assertRaisesRegex(AssertionError,'清单缺项'):
            gate.pending_items(rows[:-1])

    def test_dependency_lock_change_invalidates_installation_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);report=root/'reports/hardening/clean_environment_latest.json'
            report.parent.mkdir(parents=True);(root/'requirements.txt').write_text('changed==1')
            report.write_text(json.dumps({'status':'passed','source_sha256':{'requirements.txt':'old'}}))
            with patch.object(gate,'ROOT',root),self.assertRaisesRegex(AssertionError,'依赖锁变化'):
                gate.inspect_dependencies()

    def test_required_evidence_tamper_cannot_be_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'result.md').write_text('已经篡改')
            proof={'requirement_id':'Q3.1','status':'passed','source_sha256':{},'artifact_sha256':{'result.md':'old'},'review_scope':'人工协议夹具'}
            (root/'proof.json').write_text(json.dumps(proof))
            rows=[{'id':key,'status':'pending'} for key in gate.REQUIRED_PENDING]
            next(r for r in rows if r['id']=='Q3.1').update(status='verified',evidence='proof.json')
            with patch.object(gate,'ROOT',root),patch.object(gate,'source_hashes',return_value={}):
                self.assertIn('Q3.1',{r['id'] for r in gate.pending_items(rows)})


if __name__=='__main__':
    unittest.main()
