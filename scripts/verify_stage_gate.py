"""R0.1 放行入口：关键证据缺失、失败或源码已变化时返回非零。"""

import json
import subprocess
import sys

from verification_support import EvidenceRun, ROOT, sha256


def main():
    with EvidenceRun(ROOT / "reports/hardening", "stage_gate") as evidence:
        def unit_tests():
            code = """
import json, unittest
suite = unittest.defaultTestLoader.discover('tests')
r = unittest.TextTestRunner(verbosity=0).run(suite)
print(json.dumps({'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors)}))
"""
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
            if result.returncode:
                raise AssertionError("单元测试进程运行异常")
            output = json.loads(result.stdout.strip().splitlines()[-1])
            if output["tests"] < 18 or output["failures"] or output["errors"]:
                raise AssertionError(f"单元测试未通过：{output}")
            return output
        evidence.check("G1/G4/G5 固定答案、异常处理、验证器自检", unit_tests)
        for label in ("baseline", "mutations", "clean_environment"):
            def inspect_report():
                path = ROOT / "reports/hardening" / f"{label}_latest.json"
                report = json.loads(path.read_text())
                if report["status"] != "passed" or not report["checks"] or not all(c["passed"] for c in report["checks"]):
                    raise AssertionError(f"{label} 缺少完整通过证据")
                if report["source_sha256"] != evidence.report["source_sha256"]:
                    raise AssertionError(f"{label} 源码或依赖已变化，原报告过期，请重跑对应验证")
                return {"report": str(path.relative_to(ROOT)), "run_id": report["run_id"], "sha256": sha256(path)}
            evidence.check(f"G2–G7 {label} 报告有效且对应当前源码", inspect_report)
        def protected():
            base = "648b3c50a0792c691ead296dd834bda330a0c2e7"
            for name in ("README.md", ".gitignore", "data_sources.json"):
                original = subprocess.check_output(["git", "show", f"{base}:{name}"], cwd=ROOT)
                if (ROOT / name).read_bytes() != original:
                    raise AssertionError(f"{name} 与第一轮基准不同，需要解释并审核变更")
            tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
            if any(p.endswith((".csv", ".parquet", ".xlsx", ".zip")) for p in tracked):
                raise AssertionError("Git 索引包含原始数据或大文件")
            return {"protected_files_unchanged": True, "datasets_not_tracked": True}
        evidence.check("G8 原题、忽略规则和数据基准未改动", protected)
    print(evidence.path)
    print("允许进入 Q1.1" if evidence.report["status"] == "passed" else "禁止进入下一轮：请查看失败门槛")
    return 0 if evidence.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
