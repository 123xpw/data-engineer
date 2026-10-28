"""在临时代码副本植入指定错误，检查测试是否真能发现；不修改工作代码。"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from verification_support import EvidenceRun, ROOT

MUTATIONS = [
    ("字段顺序反转", "download_data.py", '"columns": columns}', '"columns": list(reversed(columns))}'),
    ("少计一行", "download_data.py", '"rows": rows,', '"rows": rows - 1,'),
    ("跳过校验", "download_data.py", 'if actual[key] != expected[key]:', 'if False:'),
    ("失败报成功", "run_all.py", 'result.update(status="failed", detail=detail)', 'result.update(status="passed", detail=detail)'),
    ("未执行就报成功", "run_all.py", 'result.update(status="passed", detail=action())', 'result.update(status="passed", detail={})'),
]


def run_suite(directory):
    # 结构化记录断言失败与运行错误：语法/导入异常不算成功发现业务缺陷。
    code = """
import json, unittest
suite = unittest.defaultTestLoader.discover('tests', pattern='test_baseline.py')
result = unittest.TextTestRunner(verbosity=0).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':[x.id() for x,_ in result.failures],
                  'errors':[x.id() for x,_ in result.errors]}))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=directory, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError("测试进程异常退出，不能当作捕获变异")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "hardening")
    args = parser.parse_args()
    with EvidenceRun(args.report_dir, "mutations") as evidence:
        def baseline():
            result = run_suite(ROOT)
            if result["failures"] or result["errors"]:
                raise AssertionError("未变异基线不通过，不得开展变异测试")
            return result
        if not evidence.check("未修改版本先通过", baseline):
            return 1
        for name, filename, before, after in MUTATIONS:
            def probe():
                with tempfile.TemporaryDirectory(prefix="gekko-mutant-") as directory:
                    target = Path(directory)
                    for source in ("download_data.py", "run_all.py"):
                        shutil.copyfile(ROOT / source, target / source)
                    (target / "tests").mkdir()
                    shutil.copyfile(ROOT / "tests" / "test_baseline.py", target / "tests" / "test_baseline.py")
                    path = target / filename
                    source = path.read_text()
                    if source.count(before) != 1:
                        raise AssertionError("变异位置已变化，请复核测试设计")
                    path.write_text(source.replace(before, after), encoding="utf-8")
                    result = run_suite(target)
                    # 只把明确的断言失败计为捕获；其他测试异常保留在报告中但不计分。
                    # 语法/导入错误只有 errors、没有 failures，因此仍不能通过。
                    if not result["failures"]:
                        raise AssertionError(f"变异未被可靠捕获：{result}")
                    return result
            evidence.check(name, probe)
    print(evidence.path)
    return 0 if evidence.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
