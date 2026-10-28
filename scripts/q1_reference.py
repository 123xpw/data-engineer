"""Q1.1 独立参考计算：标准库逐行计数和 Decimal，不导入 pandas 或生产统计函数。"""

from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
import re


def reference_profile(path):
    with path.open(encoding="utf-8-sig", newline="") as stream, localcontext() as context:
        context.prec = 50
        reader = csv.reader(stream, strict=True)
        columns = next(reader)
        missing = Counter()
        whitespace = Counter()
        counts = {name: Counter() for name in columns if name not in ("Quantity", "Price")}
        stats = {name: {"n": 0, "invalid": 0, "sum": Decimal(0), "squares": Decimal(0), "min": None, "max": None} for name in ("Quantity", "Price")}
        diagnostics = dict.fromkeys(("negative_quantity", "zero_quantity", "large_absolute_quantity", "negative_price", "zero_price", "non_numeric_invoice", "unusual_stock_format", "description_edge_whitespace", "duplicate_extra_rows"), 0)
        dates = {"valid_count": 0, "invalid_nonempty_count": 0, "min": None, "max": None}
        seen = set()
        rows = 0
        for record in reader:
            rows += 1
            if len(record) != len(columns):
                raise AssertionError("参考计算遇到列数不符")
            row = dict(zip(columns, record))
            numbers = {}
            for name, value in row.items():
                if value == "":
                    missing[name] += 1
                elif value.strip() == "":
                    whitespace[name] += 1
                if name in counts:
                    if value != "":
                        counts[name][value] += 1
                elif value != "":
                    try:
                        number = Decimal(value)
                        if not number.is_finite():
                            raise InvalidOperation
                    except InvalidOperation:
                        stats[name]["invalid"] += 1
                    else:
                        s = stats[name]
                        s["n"] += 1
                        s["sum"] += number
                        s["squares"] += number * number
                        s["min"] = number if s["min"] is None else min(s["min"], number)
                        s["max"] = number if s["max"] is None else max(s["max"], number)
                        numbers[name] = number
            q, p = numbers.get("Quantity"), numbers.get("Price")
            if q is not None:
                diagnostics["negative_quantity"] += q < 0
                diagnostics["zero_quantity"] += q == 0
                diagnostics["large_absolute_quantity"] += abs(q) >= 10000
            if p is not None:
                diagnostics["negative_price"] += p < 0
                diagnostics["zero_price"] += p == 0
            diagnostics["non_numeric_invoice"] += bool(row["Invoice"]) and re.fullmatch(r"[0-9]+", row["Invoice"]) is None
            diagnostics["unusual_stock_format"] += bool(row["StockCode"]) and re.fullmatch(r"[0-9]+[A-Za-z]*", row["StockCode"]) is None
            diagnostics["description_edge_whitespace"] += row["Description"] != row["Description"].strip()
            # 对每行序列化后取 SHA-256，控制百万行查重的内存占用；原始列顺序不变。
            fingerprint = hashlib.sha256(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()).digest()
            if fingerprint in seen:
                diagnostics["duplicate_extra_rows"] += 1
            else:
                seen.add(fingerprint)
            if row["InvoiceDate"]:
                try:
                    value = datetime.strptime(row["InvoiceDate"], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dates["invalid_nonempty_count"] += 1
                else:
                    dates["valid_count"] += 1
                    dates["min"] = value if dates["min"] is None else min(dates["min"], value)
                    dates["max"] = value if dates["max"] is None else max(dates["max"], value)
        result = {"rows": rows, "columns": {}, "dates": dates, "diagnostics": diagnostics}
        for bound in ("min", "max"):
            if dates[bound] is not None:
                dates[bound] = dates[bound].isoformat(sep=" ")
        for name in columns:
            item = {"missing_count": missing[name], "missing_fraction": missing[name] / rows,
                    "whitespace_only_count": whitespace[name]}
            if name in counts:
                ordered = sorted(counts[name], key=lambda value: (-counts[name][value], value))
                item["unique_nonempty"] = len(ordered)
                item["top10"] = [{"value": value, "count": counts[name][value]} for value in ordered[:10]]
            else:
                s = stats[name]
                n = s["n"]
                std = ((s["squares"] - s["sum"] ** 2 / n) / (n - 1)).sqrt() if n > 1 else None
                item["numeric"] = {"valid_count": n, "invalid_nonempty_count": s["invalid"],
                                   "min": float(s["min"]) if n else None, "max": float(s["max"]) if n else None,
                                   "mean": float(s["sum"] / n) if n else None, "std": float(std) if std is not None else None}
            result["columns"][name] = item
        return result


def compare(expected, actual, path="profile"):
    """只对均值、标准差容许预先声明的浮点误差，其余结果严格匹配。"""
    if isinstance(expected, dict):
        for key, value in expected.items():
            compare(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        if expected != actual:
            raise AssertionError(f"{path} 列表内容或顺序不符")
    elif isinstance(expected, float) and path.endswith((".mean", ".std")):
        if actual is None or not math.isclose(expected, actual, rel_tol=1e-10, abs_tol=1e-8):
            raise AssertionError(f"{path} 超出容差：{expected} / {actual}")
    elif expected != actual:
        raise AssertionError(f"{path} 不符：{expected!r} / {actual!r}")
