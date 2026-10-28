"""分阶段执行入口：当前只完成数据准备，未实现模块不会冒充成功。"""

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
    parser.add_argument("--stage", choices=("all", "data", "q1", "q2", "q3", "q4", "q5"), default="all")
    parser.add_argument("--offline", action="store_true", help="数据准备只校验本地文件")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "latest_run.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    steps = []
    if args.stage in ("all", "data"):
        for name, spec in load_sources().items():
            steps.append((f"data.{name}", lambda n=name, s=spec: prepare_dataset(n, s, args.data_dir, offline=args.offline)))
    for name in ("q1", "q2", "q3", "q4", "q5"):
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
