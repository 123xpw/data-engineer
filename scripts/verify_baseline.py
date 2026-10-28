"""从命令行外部核验真实文件；失败、超时和中断均保留本次证据。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from verification_support import EvidenceRun, ROOT, sha256, verify_outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold-download", action="store_true")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "hardening")
    args = parser.parse_args()
    with EvidenceRun(args.report_dir, "baseline") as evidence, tempfile.TemporaryDirectory(prefix="gekko-verification-") as temporary:
        temp = Path(temporary)
        spec = json.loads((ROOT / "data_sources.json").read_text())["datasets"]
        def check_cli(data_dir, statuses, code, *, stage="data", offline=True, cache=None):
            report_path = temp / "cli.json"
            report_path.unlink(missing_ok=True)
            command = [sys.executable, str(ROOT / "run_all.py"), "--stage", stage,
                       "--data-dir", str(data_dir), "--report", str(report_path),
                       "--q1-output-dir", str(temp / "q1-output")]
            if offline:
                command.append("--offline")
            environment = os.environ.copy()
            if cache:
                environment["KAGGLEHUB_CACHE"] = str(cache)
            # 从不同工作目录调用，验证路径不依赖启动位置。
            result = subprocess.run(command, cwd=temp, env=environment, timeout=900, capture_output=True, text=True)
            report = json.loads(report_path.read_text())
            expected_names = ["data.retail", "data.olist"] + (["q1.1", "q1.2", "q1.3", "q2", "q3", "q4", "q5"] if stage == "all" else [])
            if result.returncode != code or report["exit_code"] != code:
                raise AssertionError(f"退出码不符合预期 {code}，实际 {result.returncode}")
            if [r["stage"] for r in report["results"]] != expected_names or [r["status"] for r in report["results"]] != statuses:
                raise AssertionError("阶段名称或状态不符")
            external = {}
            for item in report["results"]:
                if item["stage"].startswith("data.") and item["status"] == "passed":
                    name = item["stage"].split(".")[1]
                    external[name] = verify_outputs(data_dir, spec[name]["files"], item["detail"]["files"])
            return {"actual_exit_code": result.returncode, "statuses": statuses, "independent_files": external}

        original = ROOT / "data"
        before = {str(p.relative_to(original)): sha256(p) for p in original.rglob("*.csv")}
        evidence.check("G2/G3 全部真实 CSV 独立解析与离线重跑", lambda: check_cli(original, ["passed", "passed"], 0))
        evidence.check("全流程未完成不能报告成功", lambda: check_cli(original, ["passed"] * 4 + ["not_implemented"] * 5, 2, stage="all"))
        evidence.check("缺失输入失败", lambda: check_cli(temp / "empty", ["failed", "failed"], 1))
        damaged = temp / "damaged"
        shutil.copytree(original, damaged)
        with (damaged / "online_retail_ii.csv").open("r+b") as stream:
            stream.readline()
            pos = stream.tell()
            old = stream.read(1)
            stream.seek(pos)
            stream.write(b"9" if old != b"9" else b"8")
        evidence.check("损坏输入失败且独立阶段继续", lambda: check_cli(damaged, ["failed", "passed"], 1))
        missing = temp / "missing"
        missing.mkdir()
        shutil.copyfile(original / "online_retail_ii.csv", missing / "online_retail_ii.csv")
        evidence.check("单份数据缺失保持独立状态", lambda: check_cli(missing, ["passed", "failed"], 1))
        if args.cold_download:
            evidence.check("空缓存空目录下载并独立核验", lambda: check_cli(temp / "cold", ["passed", "passed"], 0, offline=False, cache=temp / "cache"))
        def unchanged():
            after = {str(p.relative_to(original)): sha256(p) for p in original.rglob("*.csv")}
            if before != after:
                raise AssertionError("正式原始文件的内容发生变化")
            return {"unchanged_files": len(after)}
        evidence.check("G3 正式输入内容不变", unchanged)
    print(evidence.path)
    return 0 if evidence.report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
