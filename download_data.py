"""下载题目指定版本的数据，验证原始字节和 CSV 结构，不执行清洗。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger(__name__)


class DataValidationError(ValueError):
    """原始输入与已审核的数据版本不一致。"""


def inspect_csv(path: Path) -> dict:
    """逐条解析 CSV；带换行的评论仍算一条记录，不能用文本行数代替。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        columns = next(reader, [])
        if not columns or any(not name for name in columns) or len(set(columns)) != len(columns):
            raise DataValidationError(f"{path.name}：表头为空或重复")
        rows = 0
        for row in reader:
            rows += 1
            if len(row) != len(columns):
                raise DataValidationError(f"{path.name}：第 {rows} 条记录的列数不符")
    if rows == 0:
        raise DataValidationError(f"{path.name}：没有数据记录")
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size,
            "rows": rows, "columns": columns}


def verify_file(path: Path, expected: dict) -> dict:
    """校验失败时拒绝继续；不会把当前文件重新登记成正确答案。"""
    actual = inspect_csv(path)
    for key in ("sha256", "bytes", "rows", "columns"):
        if actual[key] != expected[key]:
            raise DataValidationError(f"{path.name}：{key} 与 data_sources.json 不符，请核查来源；未覆盖原文件")
    return actual


def load_sources() -> dict:
    """清单来自初次真实下载核验，常规运行只读，不能自动更新基准。"""
    return json.loads((ROOT / "data_sources.json").read_text(encoding="utf-8"))["datasets"]


def fetch_dataset(handle: str) -> Path:
    """缓存放入已被 Git 忽略的本地环境目录，不更改原仓库的忽略规则。"""
    os.environ.setdefault("KAGGLEHUB_CACHE", str(ROOT / ".venv" / "kaggle-cache"))
    import kagglehub

    return Path(kagglehub.dataset_download(handle))


def prepare_dataset(name: str, spec: dict, data_dir: Path, *, offline: bool = False) -> dict:
    """有效文件直接复用；缺失文件下载；已存在但损坏的文件明确报错。"""
    missing = []
    results = []
    for item in spec["files"]:
        target = data_dir / item["target"]
        if target.exists():
            actual = verify_file(target, item)
            results.append({"path": item["target"], "action": "verified_existing", **actual})
        else:
            missing.append(item)
    if missing and offline:
        raise FileNotFoundError(f"{name}：离线模式缺少 {len(missing)} 个文件，请先运行下载")
    if missing:
        LOG.info("下载固定版本：%s", spec["handle"])
        source_dir = fetch_dataset(spec["handle"])
        for item in missing:
            target = data_dir / item["target"]
            target.parent.mkdir(parents=True, exist_ok=True)
            # 临时文件使用同一文件系统；验证后原子替换，不留下半个正式 CSV。
            # 临时后缀仍为 .csv，以复用题目已有的忽略规则。
            fd, temporary = tempfile.mkstemp(prefix=".download-", suffix=".csv", dir=target.parent)
            os.close(fd)
            staged = Path(temporary)
            try:
                shutil.copyfile(source_dir / item["source"], staged)
                actual = verify_file(staged, item)
                staged.replace(target)
            finally:
                staged.unlink(missing_ok=True)
            results.append({"path": item["target"], "action": "downloaded", **actual})
    LOG.info("%s：%d 个文件校验通过", name, len(results))
    return {"source": spec["handle"], "files": sorted(results, key=lambda x: x["path"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("retail", "olist", "all"), default="all")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--offline", action="store_true", help="仅校验现有文件，禁止下载")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    failed = False
    for name, spec in load_sources().items():
        if args.dataset not in ("all", name):
            continue
        try:
            prepare_dataset(name, spec, args.data_dir, offline=args.offline)
        except Exception as exc:
            failed = True
            # 外部异常可能携带签名下载地址，日志只输出类型，不泄露访问凭据。
            detail = str(exc) if isinstance(exc, (DataValidationError, FileNotFoundError)) else type(exc).__name__
            LOG.error("%s 失败：%s", name, detail)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
