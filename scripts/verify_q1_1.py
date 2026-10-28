"""Q1.1 验收入口：手算、变异、独立全量复算、回归和实际输出检查。"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from q1_reference import compare, reference_profile
from verification_support import EvidenceRun, ROOT, sha256

MUTATIONS = [
    ("漏计一行", "rows = len(frame)", "rows = len(frame) - 1"),
    ("错误使用总体标准差", "finite.std(ddof=1)", "finite.std(ddof=0)"),
    ("静默裁剪字符串", "values = frame[name]", "values = frame[name].str.strip()"),
    ("并列排序错误", "(-pair[1], pair[0])", "(-pair[1], pair[0][::-1])"),
    ("缺失率分母错误", "missing.sum() / rows", "missing.sum() / max(rows - int(missing.sum()), 1)"),
]


def test_suite(directory, pattern):
    code = f"""
import json, unittest
suite = unittest.defaultTestLoader.discover('tests', pattern={pattern!r})
r = unittest.TextTestRunner(verbosity=0).run(suite)
print(json.dumps({{'tests':r.testsRun,'failures':[t.id() for t,_ in r.failures], 'errors':[t.id() for t,_ in r.errors]}}))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=directory, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError("测试进程异常，不能当作验收通过或有效捕获")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    with EvidenceRun(ROOT / "reports/q1_1", "acceptance") as evidence, tempfile.TemporaryDirectory(prefix="gekko-q11-") as folder:
        temp = Path(folder)
        original = ROOT / "data/online_retail_ii.csv"
        before = sha256(original)
        def units():
            result = test_suite(ROOT, "test*.py")
            if result["tests"] < 28 or result["failures"] or result["errors"]:
                raise AssertionError(f"手算或回归测试未通过：{result}")
            return result
        if not evidence.check("Q11-B 手算样本、独立参考实现及现有回归", units):
            return 1
        for name, old, new in MUTATIONS:
            def mutant():
                with tempfile.TemporaryDirectory(prefix="gekko-q11-mutant-") as directory:
                    project = Path(directory)
                    shutil.copyfile(ROOT / "download_data.py", project / "download_data.py")
                    for subdir in ("q1_data_quality", "scripts", "tests"):
                        (project / subdir).mkdir()
                    for relative in ("q1_data_quality/q1_code.py", "tests/test_q1_profile.py", "scripts/q1_reference.py"):
                        shutil.copyfile(ROOT / relative, project / relative)
                    target = project / "q1_data_quality/q1_code.py"
                    source = target.read_text()
                    if source.count(old) != 1:
                        raise AssertionError("错误植入位置改变，需复核变异测试")
                    target.write_text(source.replace(old, new), encoding="utf-8")
                    result = test_suite(project, "test_q1_profile.py")
                    if not result["failures"]:
                        raise AssertionError(f"没有明确断言失败，不能计为捕获：{result}")
                    return result
            evidence.check(f"Q11-F {name}", mutant)
        direct, integrated = temp / "direct", temp / "integrated"
        def cli(command):
            result = subprocess.run([sys.executable, *command], cwd=temp, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                raise AssertionError(f"运行失败：退出码 {result.returncode}")
        def reproducibility():
            cli([str(ROOT / "q1_data_quality/q1_code.py"), "--output-dir", str(direct)])
            cli([str(ROOT / "run_all.py"), "--stage", "q1.1", "--q1-output-dir", str(integrated), "--report", str(temp / "run.json")])
            files = {}
            for name in ("data_quality_metrics.json", "data_quality_report.md"):
                if (direct / name).read_bytes() != (integrated / name).read_bytes():
                    raise AssertionError(f"两个入口产物不一致：{name}")
                if (direct / name).read_bytes() != (ROOT / "q1_data_quality" / name).read_bytes():
                    raise AssertionError(f"交付产物未更新：{name}")
                files[name] = sha256(direct / name)
            return {"artifact_sha256": files, "scope": "两个入口只宣称 Q1.1 完成"}
        if not evidence.check("Q11-G 独立入口、总入口与交付产物一致", reproducibility):
            return 1
        def independent():
            expected = reference_profile(original)
            actual = json.loads((direct / "data_quality_metrics.json").read_text())
            compare(expected, actual)
            for name in ("Quantity", "Price"):
                column = actual["columns"][name]
                numeric = column["numeric"]
                if column["missing_count"] + numeric["valid_count"] + numeric["invalid_nonempty_count"] != actual["rows"]:
                    raise AssertionError(f"{name} 分类计数不守恒")
            if actual["source"]["sha256"] != before:
                raise AssertionError("统计报告标注的数据源不符")
            return {"independent_method": "csv.reader + Decimal(precision=50) + Counter；不导入生产统计函数",
                    "comparison": "计数与排序精确；均值/std rtol=1e-10, atol=1e-8", "reference": expected}
        evidence.check("Q11-A/C/D 全量独立复算与守恒", independent)
        def report_evidence():
            text = (direct / "data_quality_report.md").read_text()
            actual = json.loads((direct / "data_quality_metrics.json").read_text())
            claims = len(re.findall(r"^\d+\. \*\*", text, re.MULTILINE))
            checks = {"客户标识缺失": actual["columns"]["Customer ID"]["missing_count"],
                      "数量为负": actual["diagnostics"]["negative_quantity"],
                      "单价为负": actual["diagnostics"]["negative_price"],
                      "单价为零": actual["diagnostics"]["zero_price"],
                      "完全相同行的额外出现": actual["diagnostics"]["duplicate_extra_rows"]}
            if claims < 5:
                raise AssertionError("少于 5 个有计数的现象")
            for title, count in checks.items():
                if f"**{title}**：{count:,} 条" not in text:
                    raise AssertionError(f"报告缺少相符的证据：{title}")
            return {"observations": claims, "checked_counts": checks, "business_causes": "未声称已证明"}
        evidence.check("Q11-E 报告至少五个现象且对应统计证据", report_evidence)
        def regression():
            cli([str(ROOT / "scripts/verify_baseline.py")])
            cli([str(ROOT / "scripts/verify_mutations.py")])
            reports = {}
            for label in ("baseline", "mutations"):
                report = json.loads((ROOT / "reports/hardening" / f"{label}_latest.json").read_text())
                if report["status"] != "passed" or report["source_sha256"] != evidence.report["source_sha256"]:
                    raise AssertionError(f"{label} 回归失败或证据不对应当前源码")
                reports[label] = report["run_id"]
            return reports
        evidence.check("Q11-G 骨架真实流程与原有变异回归", regression)
        def unchanged_and_environment():
            if before != sha256(original):
                raise AssertionError("原始数据被修改")
            for name in ("README.md", ".gitignore", "data_sources.json"):
                content = subprocess.check_output(["git", "show", f"648b3c5:{name}"], cwd=ROOT)
                if content != (ROOT / name).read_bytes():
                    raise AssertionError(f"{name} 被修改")
            clean = json.loads((ROOT / "reports/hardening/clean_environment_latest.json").read_text())
            if clean["status"] != "passed" or clean["source_sha256"]["requirements.txt"] != sha256(ROOT / "requirements.txt"):
                raise AssertionError("依赖变化或缺少通过的干净环境证明，需重新验证环境")
            return {"source_unchanged": True, "reused_dependency_installation_run": clean["run_id"],
                    "limitation": "依赖未变，复用上轮安装证明；本轮新增代码没有声称在新建环境重测"}
        evidence.check("Q11-A/H 原始证据不变及环境适用范围", unchanged_and_environment)
    print(evidence.path)
    print("Q1.1 通过，可以进入 Q1.2" if evidence.report["status"] == "passed" else "禁止进入 Q1.2：存在未通过项")
    return 0 if evidence.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
