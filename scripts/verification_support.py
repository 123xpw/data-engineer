"""验证端专用工具：独立解析及持久化证据，不导入生产校验函数。"""

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import uuid

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    """关键验证不依赖可被 -O 删除的 assert。"""
    if not condition:
        raise AssertionError(message)


def require_verification_mode():
    """遗留检查仍含 assert，因此统一拒绝禁用断言的执行模式。"""
    if sys.flags.optimize:
        raise RuntimeError('禁止使用优化模式验收：请移除 -O/-OO，并清除 PYTHONOPTIMIZE 后重跑')


def sha256(path):
    # 验证端采用一次性字节读取；当前最大单文件约 95 MB，可接受。
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_independently(path):
    """pandas C 引擎与生产端 csv.reader 分离，不推断 ID 类型或缺失值。"""
    rows = 0
    columns = None
    with pd.read_csv(path, engine="c", dtype=str, keep_default_na=False, na_filter=False,
                     skip_blank_lines=False, encoding="utf-8-sig", chunksize=100_000) as reader:
        for frame in reader:
            columns = list(frame.columns)
            rows += len(frame)
    return {"rows": rows, "columns": columns, "bytes": Path(path).stat().st_size, "sha256": sha256(path)}


def verify_outputs(data_dir, expected_files, claimed_files=None):
    """读取实际文件；即使程序声称通过，也必须由验证端取得独立结果。"""
    if claimed_files is not None:
        wanted = sorted(item["target"] for item in expected_files)
        found = sorted(item["path"] for item in claimed_files)
        if found != wanted:
            raise AssertionError("报告中的文件清单缺失、重复或多出文件")
    results = []
    for item in expected_files:
        actual = inspect_independently(Path(data_dir) / item["target"])
        for key in ("columns", "rows", "bytes", "sha256"):
            if actual[key] != item[key]:
                raise AssertionError(f"{item['target']} 的 {key} 与基准不符")
        if claimed_files is not None:
            claim = next(x for x in claimed_files if x["path"] == item["target"])
            for key in actual:
                if claim[key] != actual[key]:
                    raise AssertionError(f"{item['target']} 的报告 {key} 与独立观测不符")
        results.append({"path": item["target"], **actual})
    return results


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        Path(temp).replace(path)
    finally:
        Path(temp).unlink(missing_ok=True)


def verification_source_hashes():
    """生成和消费证据共用源码清单，避免只核对生产文件而漏掉验收器变化。"""
    files = [ROOT / "requirements.txt", ROOT / "data_sources.json", ROOT / "VALIDATION_GATES.md", ROOT / "delivery_requirements.json"]
    files += sorted(ROOT.glob("*.py")) + sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))
    files += sorted((ROOT / "q1_data_quality").glob("*.py")) + sorted((ROOT / "q1_data_quality").glob("ACCEPTANCE_*.md"))
    files += sorted((ROOT / "q2_sql_analysis").glob("*.py")) + sorted((ROOT / "q2_sql_analysis").glob("*.sql"))
    files += sorted((ROOT / "q2_sql_analysis").glob("ACCEPTANCE_*.md"))
    files += [ROOT/'audit/q2_4_experiment.py', ROOT/'audit/verify_q2_4_experiment.py']
    files += [ROOT/'audit/q2_3_performance.py',ROOT/'audit/ACCEPTANCE_Q2_3_PERFORMANCE.md',
              ROOT/'audit/fixtures/q2_3_baseline_0f40889.sql',ROOT/'audit/fixtures/q2_3_materialized_candidate.sql']
    files += [ROOT/'audit/ACCEPTANCE_RELEASE_AUDIT.md']
    for directory in ('q3_etl_pipeline','q4_llm_extraction','q5_system_design'):
        files += sorted((ROOT/directory).glob('*.py'))+sorted((ROOT/directory).glob('ACCEPTANCE*.md'))
    files += [ROOT/'q5_system_design/real_time_pipeline_design.md']
    files += [ROOT/'q4_llm_extraction'/name for name in ('prompt_template.txt','pipeline_design.md','accuracy_evaluation.md','config.example.json','deepseek_config.json')]
    return {str(p.relative_to(ROOT)):sha256(p) for p in sorted(set(files)) if p.exists()}

class EvidenceRun:
    """每次运行独立编号；开始即标为运行中，每个结果立即落盘。"""

    def __init__(self, report_dir, label):
        run_id = uuid.uuid4().hex
        self.path = Path(report_dir) / f"{label}_{run_id}.json"
        self.latest = Path(report_dir) / f"{label}_latest.json"
        git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        self.report = {"run_id": run_id, "status": "running", "scope": label,
                       "started_utc": datetime.now(timezone.utc).isoformat(),
                       "python": platform.python_version(), "platform": platform.platform(),
                       "pandas": version("pandas"), "git_base": git.stdout.strip(),
                       "python_optimization_level": sys.flags.optimize,
                       "source_sha256": verification_source_hashes(),
                       "checks": []}
        self.save()
        if sys.flags.optimize:
            self.report['checks'].append({'name':'验收运行模式', 'passed':False,
                'error':'优化模式禁用 assert，拒绝执行任何验收动作'})
            self.report.update(status='failed', finished_utc=datetime.now(timezone.utc).isoformat())
            self.save()
            require_verification_mode()

    def save(self):
        atomic_json(self.path, self.report)
        atomic_json(self.latest, self.report)

    def check(self, name, action):
        try:
            result = action()
            item = {"name": name, "passed": True, "evidence": result}
        except Exception as exc:
            # 不保存下载地址、认证信息或完整外部异常文本。
            detail = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
            item = {"name": name, "passed": False, "error": detail}
        self.report["checks"].append(item)
        self.save()
        print(f"{name}: {'PASS' if item['passed'] else 'FAIL'}", flush=True)
        return item["passed"]

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is not None:
            self.report["checks"].append({"name": "运行中断", "passed": False, "error": kind.__name__})
        passed = bool(self.report["checks"]) and all(x["passed"] for x in self.report["checks"])
        self.report.update(status="passed" if passed else "failed", finished_utc=datetime.now(timezone.utc).isoformat())
        self.save()
        return False
