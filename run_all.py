"""分阶段执行入口：数据准备与 Q1 已接入，其余如实标为未完成。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import time
from typing import Callable

from download_data import ROOT, DataValidationError, load_sources, prepare_dataset

LOG = logging.getLogger(__name__)


def q1_profile(data_dir, output_dir):
    """按需导入，其他独立模块不受 Q1 依赖导入失败影响。"""
    from q1_data_quality.q1_code import run_profile
    return run_profile(data_dir / "online_retail_ii.csv", output_dir)


def q1_findings(data_dir, output_dir):
    """探索模块独立导入和运行，不依赖 Q1.1 的产物。"""
    from q1_data_quality.q1_findings import run_findings
    return run_findings(data_dir / "online_retail_ii.csv", output_dir)


def q1_strategy(output_dir):
    """交付策略文档，不将文件检查冒充业务认证或 ETL 执行。"""
    from q1_data_quality.q1_strategy import deliver_strategy
    return deliver_strategy(output_dir)


def run_steps(steps: list[tuple[str, Callable | None]]) -> tuple[list[dict], int]:
    """各阶段独立汇报；失败后继续其他独立阶段，最终仍返回失败码。"""
    results = []
    for name, action in steps:
        start = time.perf_counter()
        result = {"stage": name}
        if action is None:
            result.update(status="not_implemented", detail="尚未实现或接入；不算通过")
        else:
            try:
                result.update(status="passed", detail=action())
            except Exception as exc:
                detail = str(exc) if isinstance(exc, (DataValidationError, FileNotFoundError)) else type(exc).__name__
                result.update(status="failed", detail=detail)
        result["seconds"] = round(time.perf_counter() - start, 4)
        LOG.info("%s：%s（%.4f 秒）", name, result["status"], result["seconds"])
        if result["status"] == "failed":
            LOG.error("%s", result["detail"])
        results.append(result)
    statuses = {item["status"] for item in results}
    code = 1 if "failed" in statuses else 2 if "not_implemented" in statuses else 0
    return results, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "data", "q1", "q1.1", "q1.2", "q1.3", "q2", "q3", "q4", "q5"), default="all")
    parser.add_argument("--offline", action="store_true", help="数据准备只校验本地文件")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--q1-output-dir", type=Path, default=ROOT / "q1_data_quality")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "latest_run.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    steps = []
    if args.stage in ("all", "data"):
        for name, spec in load_sources().items():
            steps.append((f"data.{name}", lambda n=name, s=spec: prepare_dataset(n, s, args.data_dir, offline=args.offline)))
    if args.stage in ("all", "q1", "q1.1"):
        steps.append(("q1.1", lambda: q1_profile(args.data_dir, args.q1_output_dir)))
    if args.stage in ("all", "q1", "q1.2"):
        steps.append(("q1.2", lambda: q1_findings(args.data_dir, args.q1_output_dir)))
    if args.stage in ("all", "q1", "q1.3"):
        steps.append(("q1.3", lambda: q1_strategy(args.q1_output_dir)))
    for name in ("q2", "q3", "q4", "q5"):
        if args.stage in ("all", name):
            steps.append((name, None))
    results, code = run_steps(steps)
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "platform": platform.platform(),
              "requested_stage": args.stage, "exit_code": code, "results": results}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("报告：%s；退出码：%s", args.report, code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
