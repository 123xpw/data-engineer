"""从消费端挑战产物协议；人工文件只验证协议，不冒充数据实验。"""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact_manifest import ARTIFACTS, manifest_path, publish, validate_manifest


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = manifest_path(self.root, 'q2.2')

    def complete(self, folder):
        for name in ARTIFACTS['q2.2']:
            (folder/name).write_text('人工协议夹具')
        return {'load_version': 'fixture-only'}

    def test_success_then_missing_input_cannot_reuse_old_files(self):
        publish('q2.2', self.root, self.complete, run_id='first')
        validate_manifest(self.manifest, 'first')
        old = (self.root/'q2_2_results.json').read_bytes()
        with self.assertRaises(FileNotFoundError):
            publish('q2.2', self.root, self.complete, inputs=[self.root/'missing'], run_id='second')
        self.assertEqual((self.root/'q2_2_results.json').read_bytes(), old)
        for run_id in ('first', 'second'):
            with self.assertRaises(ValueError):
                validate_manifest(self.manifest, run_id)
        self.assertEqual(json.loads(self.manifest.read_text())['artifacts'], {})

    def test_no_output_or_partial_output_is_rejected_before_replacing_old(self):
        publish('q2.2', self.root, self.complete, run_id='first')
        original = (self.root/'q2_2_results.json').read_bytes()
        for action in [lambda folder: {}, lambda folder: (folder/'q2_2_results.json').write_text('半份文件')]:
            with self.assertRaises(FileNotFoundError):
                publish('q2.2', self.root, action, run_id='second')
            self.assertEqual((self.root/'q2_2_results.json').read_bytes(), original)
            with self.assertRaises(ValueError):
                validate_manifest(self.manifest, 'second')

    def test_wrong_id_source_change_and_tamper_rejected(self):
        publish('q2.2', self.root, self.complete, run_id='first')
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, 'other')
        with patch('artifact_manifest.source_hashes', return_value={'changed': 'hash'}):
            with self.assertRaises(ValueError):
                validate_manifest(self.manifest, 'first')
        (self.root/'q2_2_results.json').write_text('已替换')
        with self.assertRaises(ValueError):
            validate_manifest(self.manifest, 'first')

    def test_interrupt_and_running_state_cannot_be_read(self):
        def interrupt(folder):
            self.assertEqual(json.loads(self.manifest.read_text())['status'], 'running')
            with self.assertRaises(ValueError):
                validate_manifest(self.manifest, 'first')
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            publish('q2.2', self.root, interrupt, run_id='first')
        self.assertEqual(json.loads(self.manifest.read_text())['status'], 'failed')

    def test_independent_question_continues_after_failure(self):
        from run_all import q2_scope
        def load(data, report):
            report.write_text('{"test_only": true}')
            return {'test_only': True}
        def seller(output):
            for name in ARTIFACTS['q2.3']:
                (output/name).write_text('人工控制流夹具')
            return {'test_only': True}
        with patch('q2_sql_analysis.load_olist.load', side_effect=load), \
             patch('q2_sql_analysis.q2_1.query', side_effect=RuntimeError('人工故障')), \
             patch('q2_sql_analysis.q2_2.query', side_effect=self.complete), \
             patch('q2_sql_analysis.q2_3.query', side_effect=seller):
            result = q2_scope(self.root, self.root)
        self.assertEqual([r['status'] for r in result['results']], ['passed', 'failed', 'passed', 'passed'])
        q21 = json.loads(manifest_path(self.root, 'q2.1').read_text())
        q22 = json.loads(self.manifest.read_text())
        self.assertEqual(q21['run_id'], q22['run_id'])
        self.assertEqual(q21['status'], 'failed')
        validate_manifest(self.manifest, q22['run_id'])


if __name__ == '__main__':
    unittest.main()
