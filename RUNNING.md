# 运行说明与阶段验收

## 当前范围（2026-10-28）

第一轮只完成原始数据准备和执行骨架。Q1–Q5 尚未实现，不代表整份笔试完成。
原题 README.md 和 .gitignore 保持不变；待业务模块接入后再更新此说明。

## 环境和运行

实测 Python 3.12.13。当前仅需 Kaggle 下载库及其锁定的间接依赖。
首次下载需要能访问 Kaggle 和其文件存储服务的网络；本轮指定的公开数据实测无需登录。
如果未来服务要求认证，应按 Kaggle 官方流程在本机配置，不能用其他数据静默替换。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_all.py --stage data
python run_all.py --stage data --offline
python -m unittest discover -s tests -v
python scripts/verify_baseline.py
```

完整冷启动验证会额外使用空缓存、空临时目录重新下载两份数据：

```bash
python scripts/verify_baseline.py --cold-download
```

也可独立准备单份数据：`python download_data.py --dataset retail` 或 `--dataset olist`。
参数 `--data-dir` 指定数据目录；默认为脚本所在仓库的 data/，不依赖终端当前目录。
`--offline` 不调用下载服务，缺失文件会失败。脚本不自动修复或覆盖损坏的现有输入。

## 当前一键入口的真实行为

- `python run_all.py --stage data`：两份数据通过验证后返回 0。
- `python run_all.py`：准备两份数据，再将 Q1–Q5 标记为 not_implemented，返回 2。
- 任一阶段发生错误：该阶段标记 failed，独立阶段继续执行，最终返回 1。
- `--stage q1` 等当前只报告尚未实现，不能当成业务模块已独立运行。
- `reports/latest_run.json` 保存最近一次运行状态；`--report` 可以保留单次报告。

后续每接入一个模块，必须替换对应未实现状态并完成该模块验证。

## 数据来源与边界

`data_sources.json` 记录指定 Kaggle 版本、原文件名、目标文件名、SHA-256、字节数、CSV 记录数及表头。
基准来自首次真实下载，不是题目里的示例数字，也不是厂商提供的独立校验值。
正常执行只读基准：有差异就报错，不能自动重写基准来使测试通过。

校验保证当前输入与本次审核的版本一致，并能完整解析。它不保证每条业务记录正确。
本阶段不修改内容、不删行、不填缺失值、不把 ID 转成数字；只将零售文件名统一为题目要求的小写 ii。
Online Retail II 的原始字段是 Invoice、Price、Customer ID，后续统一字段必须明确映射。

原始 CSV 在 data/；Kaggle 缓存在 .venv/kaggle-cache/，均被现有规则忽略。
reports/ 只保存统计及校验元数据，不包含整份数据集。
测试中的小型夹具和临时损坏副本仅用于测试，不能作为业务发现或最终数据。

## 后续验收顺序

1. Q1：核验真实异常与业务假设，形成差异化清洗口径。
2. Q2：在 MySQL 8.0+ 验证 SQL 的连接粒度、指标口径和执行计划。
3. Q3：沿用 Q1 口径，验证销售、RFM、退货匹配及百万行性能。
4. Q4：先小样本验证费用和质量，再做预算内全量抽取与人工评估。
5. Q5、加分题与全流程：设计依据、业务证据、完整复现、公开 Fork 和最终提交检查。

每轮先说明假设及验收条件，再实现最小增量、测试、记录失败和修改理由。
不得以“测试通过”替代对业务结论的检查，不得捏造性能、费用、人工标注或对话。
