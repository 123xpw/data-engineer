# 运行说明与阶段验收

## 当前阶段：Q1.2

已实现数据准备、Q1.1、Q1.2；Q1.3、Q2–Q5 尚未完成。
本轮预先声明的口径与条件见 q1_data_quality/ACCEPTANCE_Q1_2.md，实际验收结果见 reports/q1_2/acceptance_latest.json。

```bash
python run_all.py --stage data
python q1_data_quality/q1_findings.py
python run_all.py --stage q1.2
python scripts/verify_q1_2.py
```

- Q1.1 仍可用 q1_data_quality/q1_code.py 或 `--stage q1.1` 独立运行，Q1.2 不依赖其输出。
- `--stage q1` 明确显示 Q1.3 未完成并返回 2；完整 run_all 返回 2，直到全部模块完成。当前应有 4 个阶段通过、5 个未实现。
- Q1.2 验收包括 38 项单元测试、五类错误植入、全量 CSV/Decimal 独立复算、两个入口产物一致、金额与行数守恒、解释前提核验和 Q1.1/骨架回归。
- 客户均额的消融实验独立脚本为 scripts/experiment_q1_2_sensitivity.py；8 个视图有手算检查，首尾结果与主报告交叉核对。
- 金额精确保留源精度，计数/字符串/金额精确比较；仅比率和均额允许绝对误差 1e-12。
- 数值验收 passed 且源码指纹一致，仅证明规定计算检查通过。后续语义审查已撤回自动放行：业务解释与清洗规则仍待补证，详见 reports/q1_2_review.md；历史通过不自动放行修改后的代码或未验证的业务规则。
- 依赖未变，复用 R0.1 的干净环境安装证明；新增代码在当前环境验证，不宣称已在新建环境再次测试。
- findings.md/JSON 是聚合结果和少量原始证据，不提交 CSV。不要修改根 README、.gitignore 或冻结数据基准来迁就实现。

以下是前期各轮的历史运行说明，不应覆盖本节的当前完成范围。

## R0.1：验证补强后的运行方法

当前仍只实现数据准备；Q1–Q5 未接入。补强验证的具体门槛见 VALIDATION_GATES.md。
新增 pandas C 引擎作为独立解析器，requirements.txt 已包含精确版本。

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/verify_mutations.py
python scripts/verify_baseline.py
python scripts/verify_clean_environment.py
python scripts/verify_stage_gate.py
```

- verify_baseline：从独立工作目录调用真实 CLI，再读取全部实际文件，不只相信成功状态。
- verify_clean_environment：创建新虚拟环境和源码副本、无缓存安装锁定依赖、下载两份真实数据、执行测试和独立核验；需要网络。
- verify_stage_gate：非零退出码表示禁止进入 Q1.1。任何被检查的代码、依赖、测试或门槛文件变化都会使旧报告失效，需要重跑相应验证。
- reports/hardening/ 下每次运行有唯一报告；*_latest.json 指向当前结果，包括 running/failed。历史失败保留，不用后续成功覆盖历史。
- 指定错误变体被捕获只证明对应风险受到测试覆盖，不是整体正确率或完整覆盖率。
- 干净虚拟环境不等于全新操作系统。当前没有其他人员独立审核，也没有跨平台兼容性结论。
- 可处理的异常会记录失败；进程被强杀可能仅留下 running，放行脚本同样拒绝。磁盘完全不可写时不能保证写出报告，此时也不能将旧证据视为本次通过。

以下保留第一轮背景，原始第一轮报告不作为补强后的放行依据。

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
