"""分阶段执行入口：Q1 已交付，Q2 已实现导入、Q2.1 与 Q2.2，其余如实标记。"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import time
import uuid
from typing import Callable

from download_data import ROOT, DataValidationError, load_sources, prepare_dataset

from artifact_manifest import RUN_ID, atomic_json, mark, publish, source_hashes

LOG = logging.getLogger(__name__)


def q1_profile(data_dir, output_dir):
    """按需导入，其他独立模块不受 Q1 依赖导入失败影响。"""
    def action(fresh):
        from q1_data_quality.q1_code import run_profile
        return run_profile(data_dir / "online_retail_ii.csv", fresh)
    return publish("q1.1", output_dir, action, inputs=[data_dir / "online_retail_ii.csv"])


def q1_findings(data_dir, output_dir):
    """探索模块独立导入和运行，不依赖 Q1.1 的产物。"""
    def action(fresh):
        from q1_data_quality.q1_findings import run_findings
        return run_findings(data_dir / "online_retail_ii.csv", fresh)
    return publish("q1.2", output_dir, action, inputs=[data_dir / "online_retail_ii.csv"])


def q1_strategy(output_dir):
    """交付策略文档，不将文件检查冒充业务认证或 ETL 执行。"""
    def action(fresh):
        from q1_data_quality.q1_strategy import deliver_strategy
        return deliver_strategy(fresh)
    return publish("q1.3", output_dir, action)


def q2_scope(data_dir, output_dir, *, stage=None):
    """Q2 内部依赖显式处理，导入失败不拿旧批次冒充本次成功。"""
    run_id = RUN_ID.get() or uuid.uuid4().hex
    requested = [stage] if stage else ['q2.1', 'q2.2']
    details = []
    for name in requested:
        mark(output_dir, name, "running", run_id=run_id)
    try:
        def load_action(fresh):
            from q2_sql_analysis.load_olist import load
            return load(data_dir, fresh / "load_report.json")
        loaded = publish("q2.load", output_dir, load_action, run_id=run_id)
        details.append({"stage": "q2.load", "status": "passed", "detail": loaded})
    except Exception as exc:
        for name in requested:
            mark(output_dir, name, "blocked_dependency", run_id=run_id, error=type(exc).__name__)
        return {"stage_completion": "failed", "results": [{"stage": "q2.load", "status": "failed", "error": type(exc).__name__},
                *({"stage": name, "status": "blocked_dependency"} for name in requested)]}
    for name in requested:
        try:
            def query_action(fresh):
                if name == 'q2.1':
                    from q2_sql_analysis.q2_1 import query
                else:
                    from q2_sql_analysis.q2_2 import query
                return query(fresh)
            result = publish(name, output_dir, query_action, inputs=[output_dir / "load_report.json"], run_id=run_id)
            details.append({"stage": name, "status": "passed", "detail": result})
        except Exception as exc:
            details.append({"stage": name, "status": "failed", "error": type(exc).__name__})
    if any(item['status'] == 'failed' for item in details):
        return {"stage_completion": "failed", "results": details}
    if stage:
        return {"results": details, "scope": f"仅九表导入与 {stage}"}
    details.extend({"stage": name, "status": "not_implemented"} for name in ("q2.3", "q2.4"))
    return {"stage_completion": "partial", "results": details}


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
                detail = action()
                status = detail.get("stage_completion", "passed") if isinstance(detail, dict) else "passed"
                if status not in ("passed", "partial", "failed"):
                    raise ValueError("阶段返回了未定义状态")
                result.update(status=status, detail=detail)
            except Exception as exc:
                detail = str(exc) if isinstance(exc, (DataValidationError, FileNotFoundError)) else type(exc).__name__
                result.update(status="failed", detail=detail)
        result["seconds"] = round(time.perf_counter() - start, 4)
        LOG.info("%s：%s（%.4f 秒）", name, result["status"], result["seconds"])
        if result["status"] == "failed":
            LOG.error("%s", result["detail"])
        results.append(result)
    statuses = {item["status"] for item in results}
    code = 1 if "failed" in statuses else 2 if statuses & {"not_implemented", "partial"} else 0
    return results, code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "data", "q1", "q1.1", "q1.2", "q1.3", "q2", "q2.1", "q2.2", "q3", "q4", "q5"), default="all")
    parser.add_argument("--offline", action="store_true", help="数据准备只校验本地文件")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--q1-output-dir", type=Path, default=ROOT / "q1_data_quality")
    parser.add_argument("--q2-output-dir", type=Path, default=ROOT / "q2_sql_analysis")
    parser.add_argument("--report", type=Path, default=ROOT / "reports" / "latest_run.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_id = uuid.uuid4().hex
    RUN_ID.set(run_id)
    atomic_json(args.report, {"run_id": run_id, "status": "running", "requested_stage": args.stage})
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
    if args.stage in ("all", "q2", "q2.1", "q2.2"):
        selected = args.stage if args.stage in ('q2.1', 'q2.2') else None
        steps.append((selected or 'q2', lambda: q2_scope(args.data_dir, args.q2_output_dir, stage=selected)))
    for name in ("q3", "q4", "q5"):
        if args.stage in ("all", name):
            steps.append((name, None))
    results, code = run_steps(steps)
    report = {"run_id": run_id, "status": "passed" if code == 0 else "failed" if code == 1 else "partial",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "platform": platform.platform(),
              "requested_stage": args.stage, "exit_code": code, "results": results,
              "source_sha256": source_hashes(),
              "output_directories": {"q1": str(args.q1_output_dir.resolve()), "q2": str(args.q2_output_dir.resolve())}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.report, report)
    LOG.info("报告：%s；退出码：%s", args.report, code)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
