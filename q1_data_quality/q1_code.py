"""Q1.1：保留原始记录的数据质量初探，尚不实施清洗。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from download_data import load_sources, verify_file

COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]
SEMANTICS = {"Invoice": "发票标识", "StockCode": "商品或业务编码", "Description": "描述文本",
             "Quantity": "数量", "InvoiceDate": "日期时间（源文件未提供时区）", "Price": "单价",
             "Customer ID": "客户标识", "Country": "国家文本"}


def profile_frame(frame: pd.DataFrame) -> dict:
    """只产生统计，不删行、不去重、不填充缺失、不裁剪原始字符串。"""
    if list(frame.columns) != COLUMNS or len(frame) == 0:
        raise ValueError("需要完整的 8 列以及至少一条数据记录")
    rows = len(frame)
    result = {"rows": rows, "columns": {}}
    numbers = {}
    for name in COLUMNS:
        values = frame[name]
        missing = values.eq("")
        item = {"read_dtype": str(values.dtype), "semantic_type": SEMANTICS[name],
                "missing_count": int(missing.sum()), "missing_fraction": float(missing.sum() / rows),
                "whitespace_only_count": int((~missing & values.str.strip().eq("")).sum())}
        if name in ("Quantity", "Price"):
            parsed = pd.to_numeric(values, errors="coerce").astype(float)
            valid = np.isfinite(parsed) & ~missing
            numbers[name] = parsed.where(valid)
            finite = parsed[valid]
            n = len(finite)
            item["numeric"] = {"valid_count": n, "invalid_nonempty_count": int((~missing & ~valid).sum()),
                               "min": float(finite.min()) if n else None,
                               "max": float(finite.max()) if n else None,
                               "mean": float(finite.mean()) if n else None,
                               "std": float(finite.std(ddof=1)) if n > 1 else None}
        else:
            counts = values[~missing].value_counts().to_dict()
            ranking = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
            item["unique_nonempty"] = len(counts)
            item["top10"] = [{"value": value, "count": int(count)} for value, count in ranking[:10]]
        result["columns"][name] = item
    dates = pd.to_datetime(frame["InvoiceDate"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    result["dates"] = {"valid_count": int(dates.notna().sum()),
                       "invalid_nonempty_count": int((frame["InvoiceDate"].ne("") & dates.isna()).sum()),
                       "min": dates.min().isoformat(sep=" ") if dates.notna().any() else None,
                       "max": dates.max().isoformat(sep=" ") if dates.notna().any() else None}
    result["diagnostics"] = {
        "negative_quantity": int(numbers["Quantity"].lt(0).sum()),
        "zero_quantity": int(numbers["Quantity"].eq(0).sum()),
        "large_absolute_quantity": int(numbers["Quantity"].abs().ge(10000).sum()),
        "negative_price": int(numbers["Price"].lt(0).sum()),
        "zero_price": int(numbers["Price"].eq(0).sum()),
        "non_numeric_invoice": int((frame["Invoice"].ne("") & ~frame["Invoice"].str.fullmatch(r"[0-9]+")).sum()),
        "unusual_stock_format": int((frame["StockCode"].ne("") & ~frame["StockCode"].str.fullmatch(r"[0-9]+[A-Za-z]*")).sum()),
        "description_edge_whitespace": int(frame["Description"].ne(frame["Description"].str.strip()).sum()),
        "duplicate_extra_rows": int(frame.duplicated(keep="first").sum()),
    }
    return result


def observations(profile):
    """先报告可复算现象；业务解释只列为下一步需要检验的可能性。"""
    n = profile["rows"]
    d = profile["diagnostics"]
    candidates = [
        ("客户标识缺失", profile["columns"]["Customer ID"]["missing_count"], "客户分析不能直接覆盖这些记录；下一步比较其金额和国家分布，不能仅因缺失就删除。"),
        ("商品描述缺失", profile["columns"]["Description"]["missing_count"], "需结合商品编码和数量检查是否属于调整记录；当前不猜测或补写描述。"),
        ("数量为负", d["negative_quantity"], "可能包含退货或冲销，需核验发票前缀；负值不自动等于数据错误。"),
        ("数量为零", d["zero_quantity"], "需检查是否有业务记录意义；不能把它计为正常购买数量。"),
        ("单价为负", d["negative_price"], "需结合描述和编码解释调整含义；此时直接删除可能改变金额口径。"),
        ("单价为零", d["zero_price"], "可能是赠品、补发或录入问题，目前没有证据区分，需保留原始记录核查。"),
        ("发票号并非纯数字", d["non_numeric_invoice"], "发票号不能当普通数值字段；Q1.2 再拆解前缀及对应业务。"),
        ("商品编码格式候选异常", d["unusual_stock_format"], "编码不符合纯数字或数字后接字母模式；这只是筛选，不能直接宣称全部是非商品。"),
        ("描述两端存在空白", d["description_edge_whitespace"], "原字符串计数可能把相似描述分开；规范化需在衍生层进行，不能覆盖原始证据。"),
        ("完全相同行的额外出现", d["duplicate_extra_rows"], "相同行可能来自复制，也可能是不同的业务明细；缺少唯一行键，尚不能无条件去重。"),
        ("数量绝对值达到探索阈值 10000", d["large_absolute_quantity"], "需查看极端交易及相反数量的记录；探索阈值不是删除阈值。"),
    ]
    return [{"phenomenon": title, "count": count, "fraction": count / n, "interpretation": text}
            for title, count, text in candidates if count]


def render_report(profile):
    """从同一机器可读结果生成中文报告，不手工抄写业务数字。"""
    def show(value):
        return "不适用" if value is None else f"{value:.12g}"
    lines = ["# Q1.1 数据质量初探", "", "范围：只观察原始数据，不清洗，不代表 Q1.2/Q1.3 已完成。", "",
             f"数据版本：{profile['source']['handle']}；实际记录数：{profile['rows']:,}。",
             f"原文件 SHA-256：`{profile['source']['sha256']}`。", "", "## 统计口径与思考", "",
             "我先把全部字段按原始字符串读取，以免把标识符误当金额或丢失前导零。表中的读取类型与业务含义分开列出；数值统计仅转换 Quantity 和 Price。Customer ID 的 .0 后缀目前保留，不对身份作合并。", "",
             "缺失只按空字符串计数，空白文本单列。NA、NULL 等可能是实际文本，不能交给解析器自动填空。唯一值和频次也保留大小写、两端空白，避免在探索阶段悄悄完成有损清洗。", "",
             "数值转换失败与原始缺失分开，统计分母为有效有限数值的数量；缺失率分母为全部记录。标准差采用样本标准差 ddof=1；有效数不足两条时不适用。报告保留 min/max，不用截尾提前掩盖极端业务。", "",
             "日期只按源文件展示格式解析，不凭国家推断时区。完全相同行只标记额外出现次数，因为没有可靠明细行主键，无法证明重复就一定多余。下面的可疑现象都只是待调查对象，不能据此直接删除记录。", "",
             "TOP 10 按频次降序、原字符串升序处理并列，保证重跑稳定。原始字节基准只保证输入版本一致，不能证明业务含义正确。后续先检查会影响金额和客户口径的异常，并用 Q1.2 的具体记录验证假设。", "",
             "## 类型与缺失", "", "| 字段 | 读取类型 | 业务含义 | 缺失数 | 缺失率 | 纯空白数 |", "|---|---|---|---:|---:|---:|"]
    for name, item in profile["columns"].items():
        lines.append(f"| {name} | {item['read_dtype']} | {item['semantic_type']} | {item['missing_count']:,} | {item['missing_fraction']:.6%} | {item['whitespace_only_count']:,} |")
    lines += ["", "## 数值分布", "", "| 字段 | 有效数 | 非空转换失败数 | min | max | mean | std（ddof=1） |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name in ("Quantity", "Price"):
        x = profile["columns"][name]["numeric"]
        lines.append(f"| {name} | {x['valid_count']:,} | {x['invalid_nonempty_count']:,} | {show(x['min'])} | {show(x['max'])} | {show(x['mean'])} | {show(x['std'])} |")
    x = profile["dates"]
    lines += ["", f"日期有效记录：{x['valid_count']:,}；非空解析失败：{x['invalid_nonempty_count']:,}；范围：{x['min']} 至 {x['max']}。", "", "## 字符串唯一值与 TOP 10", "", "空字符串不参与唯一值及频次统计。值以 JSON 字符串显示，保留空白与转义。"]
    for name, item in profile["columns"].items():
        if "top10" not in item:
            continue
        lines += ["", f"### {name}：{item['unique_nonempty']:,} 个非空唯一值", "", "| 原始值 | 次数 |", "|---|---:|"]
        for top in item["top10"]:
            value = json.dumps(top["value"], ensure_ascii=False).replace("|", "\\|")
            lines.append(f"| {value} | {top['count']:,} |")
    lines += ["", "## 有证据的可疑现象", ""]
    for i, item in enumerate(observations(profile), 1):
        lines.append(f"{i}. **{item['phenomenon']}**：{item['count']:,} 条，占全部记录 {item['fraction']:.6%}。{item['interpretation']}")
    lines += ["", "以上现象可能重叠，其计数不能直接相加为‘脏数据总量’。业务成因尚未证明；下一轮再逐条核验。", ""]
    return "\n".join(lines)


def run_profile(input_path, output_dir):
    spec = load_sources()["retail"]
    expected = spec["files"][0]
    verify_file(Path(input_path), expected)
    frame = pd.read_csv(input_path, dtype=str, keep_default_na=False, na_filter=False, skip_blank_lines=False, encoding="utf-8-sig")
    profile = profile_frame(frame)
    profile["source"] = {"handle": spec["handle"], "sha256": expected["sha256"]}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "data_quality_metrics.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (output_dir / "data_quality_report.md").write_text(render_report(profile), encoding="utf-8")
    return {"rows": profile["rows"], "observations": len(observations(profile)), "scope": "仅 Q1.1", "output_dir": str(output_dir)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/online_retail_ii.csv")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(run_profile(args.input, args.output_dir), ensure_ascii=False))


if __name__ == "__main__":
    main()
