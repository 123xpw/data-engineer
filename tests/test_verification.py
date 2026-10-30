"""验证器本身也需接受测试；不以被测函数生成固定答案。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.verification_support import EvidenceRun, ROOT, inspect_independently, verify_outputs


class VerificationTests(unittest.TestCase):
    def test_optimized_modes_fail_before_action_and_replace_stale_success(self):
        for flag,value,level in [('-O',None,1),('-OO',None,2),(None,'1',1),(None,'2',2)]:
            with self.subTest(flag=flag,environment=value),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);history=root/'mode_old.json';latest=root/'mode_latest.json'
                history.write_text('{"status":"passed","run_id":"old"}')
                latest.write_bytes(history.read_bytes())
                original=history.read_bytes();marker=root/'action_ran'
                code="from scripts.verification_support import EvidenceRun\nfrom pathlib import Path\nwith EvidenceRun(Path("+repr(folder)+"), 'mode') as e:\n Path("+repr(str(marker))+").touch()\n e.check('action', lambda: {})\n"
                env=os.environ.copy();env.pop('PYTHONOPTIMIZE',None)
                if value:env['PYTHONOPTIMIZE']=value
                cmd=[sys.executable]+([flag] if flag else [])+['-c',code]
                r=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('禁止使用优化模式验收',r.stderr)
                self.assertFalse(marker.exists())
                report=json.loads(latest.read_text())
                self.assertEqual(report['status'],'failed')
                self.assertEqual(report['python_optimization_level'],level)
                self.assertNotEqual(report['run_id'],'old')
                self.assertEqual(history.read_bytes(),original)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "example.csv"
        self.path.write_bytes(b'id,comment\n001,"first\nsecond"\n002,normal\n')
        self.expected = {"columns": ["id", "comment"], "rows": 2, "bytes": 41,
                         "sha256": "6563bb86dcce481e9fec9d1e94d0f9669d4f971fc7a4de0c496bbf7b940943ce"}

    def test_second_parser_matches_fixed_answer(self):
        self.assertEqual(inspect_independently(self.path), self.expected)

    def test_claimed_success_with_missing_output_is_rejected(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            verify_outputs(self.root, [{"target": "example.csv", **self.expected}],
                           [{"path": "example.csv", **self.expected}])

    def test_report_cannot_lie_about_real_output(self):
        with self.assertRaisesRegex(AssertionError, "报告 rows"):
            verify_outputs(self.root, [{"target": "example.csv", **self.expected}],
                           [{"path": "example.csv", **self.expected, "rows": 123}])

    def test_failure_is_saved_before_context_finishes(self):
        with EvidenceRun(self.root, "fixture") as run:
            def fail():
                raise AssertionError("人工故障，不是业务结果")
            self.assertFalse(run.check("失败应被记录", fail))
            saved = json.loads(run.path.read_text())
            self.assertFalse(saved["checks"][0]["passed"])
        self.assertEqual(json.loads(run.latest.read_text())["status"], "failed")

    def test_interruption_replaces_old_success_with_new_failed_run(self):
        with EvidenceRun(self.root, "fixture") as old:
            old.check("人工成功夹具", lambda: {})
        with self.assertRaises(RuntimeError):
            with EvidenceRun(self.root, "fixture") as new:
                self.assertEqual(json.loads(new.latest.read_text())["status"], "running")
                raise RuntimeError("人工中断")
        self.assertNotEqual(old.path, new.path)
        self.assertEqual(json.loads(new.latest.read_text())["status"], "failed")
        self.assertEqual(json.loads(old.path.read_text())["status"], "passed")

    def test_real_verifier_process_failure_leaves_report_and_nonzero_exit(self):
        # 复制代码到没有数据的临时仓库，验证真正的子进程失败，而非只 mock 状态。
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "data").mkdir()
        for name in ("run_all.py", "download_data.py", "artifact_manifest.py", "data_sources.json"):
            shutil.copyfile(ROOT / name, repo / name)
        shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        reports = repo / "reports"
        reports.mkdir()
        (reports / "baseline_latest.json").write_text('{"status":"passed","run_id":"old"}')
        result = subprocess.run([sys.executable, str(repo / "scripts" / "verify_baseline.py"),
                                 "--report-dir", str(reports)], cwd=repo, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads((reports / "baseline_latest.json").read_text())
        self.assertNotEqual(report["run_id"], "old")
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any(not check["passed"] for check in report["checks"]))


if __name__ == "__main__":
    unittest.main()
