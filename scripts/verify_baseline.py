"""在临时副本上验证真实数据流程；故障注入不会修改正式数据。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold-download", action="store_true", help="额外使用空缓存和空目录联网下载")
    args = parser.parse_args()
    records = []
    def check(name, data_dir, expected_code, expected_statuses, *, offline=True, stage="data", cache=None):
        command = [sys.executable, str(ROOT / "run_all.py"), "--stage", stage,
                   "--data-dir", str(data_dir), "--report", str(report_path)]
        if offline:
            command.append("--offline")
        environment = os.environ.copy()
        if cache:
            environment["KAGGLEHUB_CACHE"] = str(cache)
        report_path.unlink(missing_ok=True)
        result = subprocess.run(command, cwd=ROOT, env=environment, timeout=900)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        statuses = [item["status"] for item in report["results"]]
        passed = result.returncode == expected_code and statuses == expected_statuses
        records.append({"case": name, "passed": passed, "expected_exit_code": expected_code,
                        "actual_exit_code": result.returncode, "run": report})
        if not passed:
            raise AssertionError(f"{name} 未满足预期：{result.returncode}, {statuses}")

    with tempfile.TemporaryDirectory(prefix="gekko-baseline-") as temporary:
        temp = Path(temporary)
        report_path = temp / "report.json"
        original = ROOT / "data"
        before = {str(p.relative_to(original)): p.stat().st_mtime_ns for p in original.rglob("*.csv")}
        check("真实数据离线重跑", original, 0, ["passed", "passed"])
        after = {str(p.relative_to(original)): p.stat().st_mtime_ns for p in original.rglob("*.csv")}
        if before != after:
            raise AssertionError("重跑不应修改原始 CSV")
        check("全流程如实报告未实现模块", original, 2, ["passed", "passed"] + ["not_implemented"] * 5, stage="all")
        check("空目录离线失败", temp / "empty", 1, ["failed", "failed"])
        damaged = temp / "damaged"
        shutil.copytree(original, damaged)
        # 仅改副本第一条记录的一位发票号，字节数和结构不变，但校验值必须变化。
        with (damaged / "online_retail_ii.csv").open("r+b") as stream:
            stream.readline()
            position = stream.tell()
            old = stream.read(1)
            stream.seek(position)
            stream.write(b"9" if old != b"9" else b"8")
        check("零售输入损坏不阻断独立 Olist 校验", damaged, 1, ["failed", "passed"])
        missing = temp / "missing"
        missing.mkdir()
        shutil.copyfile(original / "online_retail_ii.csv", missing / "online_retail_ii.csv")
        check("仅缺 Olist 时保留零售校验成功结果", missing, 1, ["passed", "failed"])
        if args.cold_download:
            check("空缓存空目录真实下载", temp / "cold", 0, ["passed", "passed"],
                  offline=False, cache=temp / "cold-cache")
    destination = ROOT / "reports" / ("baseline_cold_verification.json" if args.cold_download else "baseline_verification.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"scope": "数据准备骨架，不代表 Q1–Q5 完成", "checks": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"通过 {len(records)} 项真实数据流程检查；报告：{destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
