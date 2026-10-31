"""用缺项、过期证据挑战放行器；不以全绿计数替代需求覆盖。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import release_check as gate


class ReleaseTests(unittest.TestCase):
    def complete_fixture(self):
        stages=['data.retail','data.olist','q1.1','q1.2','q1.3','q2','q3','q4','q5']
        report={'requested_stage':'all','exit_code':0,'status':'passed','results':[{'stage':s,'status':'passed'} for s in stages]}
        next(r for r in report['results'] if r['stage']=='q2')['detail']={'results':[{'stage':s,'status':'passed'} for s in ['q2.load','q2.1','q2.2','q2.3','q2.4']]}
        return report

    def test_duplicate_failed_stage_cannot_be_overwritten(self):
        for child in (False,True):
            with self.subTest(child=child):
                report=self.complete_fixture()
                rows=next(r for r in report['results'] if r['stage']=='q2')['detail']['results'] if child else report['results']
                rows.insert(0,{'stage':'q2.3' if child else 'q4','status':'failed'})
                with self.assertRaisesRegex(AssertionError,'重复'):
                    gate.inspect_complete_execution(report)

    def test_complete_report_rejects_contradictory_header_and_extra_stage(self):
        for change in ('exit','status','extra','partial','bool_exit','float_exit'):
            with self.subTest(change=change):
                report=self.complete_fixture()
                if change=='exit':report['exit_code']=1
                elif change=='status':report['status']='failed'
                elif change=='extra':report['results'].append({'stage':'unexpected','status':'passed'})
                elif change=='partial':next(r for r in report['results'] if r['stage']=='q2')['status']='partial'
                else:report['exit_code']=False if change=='bool_exit' else 0.0
                with self.assertRaises(AssertionError):gate.inspect_complete_execution(report)

    def test_program_requirement_rejects_empty_checks_and_irrelevant_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'irrelevant.md').write_text('不是 Q3 输出')
            proof={'requirement_id':'Q3.1','status':'passed','production_source_sha256':{},'source_sha256':{},
                   'artifact_sha256':{'irrelevant.md':gate.digest(root/'irrelevant.md')},'checks':[],'review_scope':'负控制夹具'}
            (root/'proof.json').write_text(json.dumps(proof))
            rows=[{'id':k,'status':'pending'} for k in gate.REQUIRED_PENDING]
            next(r for r in rows if r['id']=='Q3.1').update(status='verified',evidence='proof.json')
            with patch.object(gate,'ROOT',root),patch.object(gate,'source_hashes',return_value={}):
                self.assertIn('Q3.1',{r['id'] for r in gate.pending_items(rows)})

    def test_missing_verified_proof_stays_pending_with_other_requirements(self):
        rows=[{'id':k,'status':'pending'} for k in gate.REQUIRED_PENDING]
        next(r for r in rows if r['id']=='Q3.1').update(status='verified',evidence='does-not-exist.json')
        pending=gate.pending_items(rows)
        self.assertEqual({r['id'] for r in pending},gate.REQUIRED_PENDING)

    def test_valid_program_envelope_then_structural_damage(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stage='Q5.1';_,_,names,artifacts=gate.CONTRACTS[stage]
            hashes={}
            for name in artifacts:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('合成产物，不代表业务验收')
                hashes[name]=gate.digest(p)
            proof={'run_id':'fixture','status':'passed','requirement_id':stage,'source_sha256':{},'production_source_sha256':{},
                   'review_scope':'只检验封套结构的合成夹具','checks':[{'name':n,'passed':True} for n in names],'artifact_sha256':hashes}
            with patch.object(gate,'ROOT',root),patch.object(gate,'source_hashes',return_value={}):
                self.assertEqual(gate.inspect_subquestion(stage,{},proof)['run_id'],'fixture')
                for mode in ('empty_checks','duplicate','string_pass','empty_artifacts','unrelated'):
                    bad=copy.deepcopy(proof)
                    if mode=='empty_checks':bad['checks']=[]
                    elif mode=='duplicate':bad['checks']*=2
                    elif mode=='string_pass':bad['checks'][0]['passed']='true'
                    elif mode=='empty_artifacts':bad['artifact_sha256']={}
                    else:bad['artifact_sha256']={'irrelevant.md':'not-a-real-hash'}
                    with self.subTest(mode=mode),self.assertRaises(AssertionError):gate.inspect_subquestion(stage,{},bad)

    def test_verified_proof_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'project';root.mkdir();(base/'outside.json').write_text('{}')
            rows=[{'id':k,'status':'pending'} for k in gate.REQUIRED_PENDING]
            next(r for r in rows if r['id']=='Q3.1').update(status='verified',evidence='../outside.json')
            with patch.object(gate,'ROOT',root):
                self.assertIn('Q3.1',{r['id'] for r in gate.pending_items(rows)})

    def test_current_input_corruption_cannot_reuse_old_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'data';data.mkdir();spec={'datasets':{}}
            for name in ('retail','olist'):
                p=data/(name+'.csv');p.write_bytes(b'a,b\n1,2\n')
                spec['datasets'][name]={'files':[{'target':p.name,'bytes':p.stat().st_size,'sha256':gate.digest(p)}]}
            (root/'data_sources.json').write_text(json.dumps(spec))
            with patch.object(gate,'ROOT',root):
                self.assertEqual(gate.inspect_inputs()['verified_files'],2)
                (data/'retail.csv').write_bytes(b'a,b\n9,2\n')
                with self.assertRaisesRegex(AssertionError,'当前输入缺失或已改变'):gate.inspect_inputs()

    def test_duplicate_json_fields_and_nonstandard_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'proof.json'
            for text in ('{"status":"failed","status":"passed"}','{"seconds":NaN}','{"seconds":Infinity}'):
                with self.subTest(text=text):
                    p.write_text(text)
                    with self.assertRaises(ValueError):gate.read(p)

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

    def test_zero_exit_cannot_hide_missing_business_stage(self):
        report={'requested_stage':'all','exit_code':0,'status':'passed','results':[{'stage':key,'status':'passed'} for key in ('data.retail','data.olist','q1.1','q1.2','q1.3','q2','q3','q5')]}
        with self.assertRaisesRegex(AssertionError,'缺少必答阶段'):
            gate.inspect_complete_execution(report)

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
