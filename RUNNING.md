# 运行说明与阶段验收

当前工作安排、时间上限和本人学习动作统一见 [PROJECT_CONTROL.md](PROJECT_CONTROL.md)。

> 整项目仍不可完整交付。R1–R4 已完成本次已知缺陷修复和统一门槛验收；各轮标准、结果、失败记录见 [repairs/PROGRESS.md](repairs/PROGRESS.md)。原审查见 [audit/PROJECT_REVIEW.md](audit/PROJECT_REVIEW.md)，用于保留发现过程，不覆盖新的修复结果。

## 当前阶段：Q1、Q2.1/Q2.2 已实现；Q2.3 独立入口通过，默认整合待完成

Q1.1 的质量报告、Q1.2 的探索与补证、Q1.3 的清洗策略已接入独立入口；真实 MySQL 九表导入、Q2.1 翻译缺口和 Q2.2 月度成交已实现。Q2.3 独立 SQL/CLI 与单题入口已通过，默认全入口尚未整合；Q2.4、Q3–Q5 尚未完成。Q2 本轮证据与限制见 reports/q2_2_validation.md，数据模型与 Docker 前置要求见 q2_sql_analysis/DATA_MODEL.md。

```bash
python run_all.py --stage data
python run_all.py --stage q1.1
python run_all.py --stage q1.2
python run_all.py --stage q1.3
python run_all.py --stage q1
python scripts/verify_q1_3.py
python run_all.py --stage q2.1
python scripts/verify_q2_1.py
python run_all.py --stage q2.2
python scripts/verify_q2_2.py
```

- Q1.3 的独立命令为 `python q1_data_quality/q1_strategy.py`，只交付文档，不实施 ETL 或自动认证业务解释；其正文、规则审查表及口径见 q1_data_quality/。
- `--stage q1` 完成三个题目的交付入口并返回 0；`--stage q2.1` 或 `--stage q2.2` 完成导入及对应查询后返回 0；`--stage q2` 返回 partial/退出码 2。完整 run_all 仍返回 2，当前 5 个阶段完成、Q2 部分完成、Q3–Q5 未实现。入口 passed 不表示业务规则已获批准。
- Q1.3 验收核对文档与字数、隔离运行、缺件失败、真实反例，并回归此前计算检查。每轮条件见 ACCEPTANCE_*.md；机器报告在 reports/ 对应目录，历史证据保留。
- Q1.2 补证单独运行 `python scripts/verify_q1_review.py`；逐记录归属仅写本地忽略目录 .venv/q1-review/。字节一致、独立复算和定向变异均有适用边界，不能替代业务审查。
- Q1.3 新发现正向候选保留等额取消对应的正单，可能影响最近购买、频次和推荐偏好。策略因此要求核对订单事件；未实现或认证自动匹配。语义审查仍由同一 AI 完成。
- 不提交 CSV，不改根 README、.gitignore 或冻结数据基准。新增 PyMySQL 1.1.2 已补全新 Python 环境安装、空缓存下载验证；该实验复用本机项目数据库，不是全新操作系统或全新 MySQL 实例。
- Q2.1 独立入口 `python q2_sql_analysis/q2_1.py` 会重新导入；已有完整批次可加 `--skip-load`。从零执行先安装锁定依赖并准备 Docker；`python run_all.py` 包含数据下载和项目数据库初始化。尚未实现的后续阶段不会被伪装成功。
- Q2.2 独立入口 `python q2_sql_analysis/q2_2.py` 同样支持 `--skip-load`，输出月度 JSON 和中文 Markdown；缺送达时间只退出时长分母。Q2.1 查询失败不会阻止共享导入成功后的 Q2.2 独立查询。

以下是前期各轮的历史运行说明，不应覆盖本节的当前完成范围。

## 历史：R0.1 验证补强后的运行方法

当时仅实现数据准备；Q1–Q5 尚未接入。补强验证的具体门槛见 VALIDATION_GATES.md。
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
- verify_stage_gate：原 R0 行为已退役，现在转发到 release_check 默认的完整提交检查；历史报告不删除，也不再用于批准进入 Q1.1。
- reports/hardening/ 下每次运行有唯一报告；*_latest.json 指向当前结果，包括 running/failed。历史失败保留，不用后续成功覆盖历史。
- 指定错误变体被捕获只证明对应风险受到测试覆盖，不是整体正确率或完整覆盖率。
- 干净虚拟环境不等于全新操作系统。当前没有其他人员独立审核，也没有跨平台兼容性结论。
- 可处理的异常会记录失败；进程被强杀可能仅留下 running，放行脚本同样拒绝。磁盘完全不可写时不能保证写出报告，此时也不能将旧证据视为本次通过。

以下保留第一轮背景，原始第一轮报告不作为补强后的放行依据。

## 历史：第一轮范围（2026-10-28）

第一轮只完成原始数据准备和执行骨架。Q1–Q5 尚未实现，不代表整份笔试完成。
原题 README.md 和 .gitignore 保持不变；待业务模块接入后再更新此说明。

## 环境和运行

实测 Python 3.12.13。第一轮仅需 Kaggle 下载库及其锁定的间接依赖。
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

## 历史：第一轮入口行为

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

## R3：读取本轮产物

正式 Q1/Q2 CLI 会在输出目录生成 `q1_1_manifest.json`、`q2_2_manifest.json` 等清单。总入口的 `reports/latest_run.json` 包含本轮 `run_id`；各题共享此编号。独立入口有自身编号，见其清单。`passed` 表示约定文件已完整发布，不表示全部项目完成。

消费端使用 `python artifact_manifest.py --manifest <清单路径> --run-id <本轮编号>` 校验。失败后旧 JSON/Markdown 可以留存供调查，但失败清单、错误编号或哈希不一致必须拒绝。不得只凭文件存在来验收。核心计算函数仍可用于测试，不等于正式发布入口。修复过程与边界见 repairs/R3_RESULT.md。


## R4：当前统一验收入口

```bash
python release_check.py --scope implemented --refresh
python release_check.py --scope implemented
python release_check.py
```

第一条重跑当前源码的独立业务回归及正式全入口；新的候选输出保存在本地忽略目录 `.venv/release-runs/`，位置与本轮编号写入 `reports/release_execution.json`。后两条核对已有证据、源码指纹和实际文件；不冒充重新执行。复制到另一台机器后需重新 refresh，缺少本地候选文件应失败。

- implemented 通过，只允许在已实现 Q1、九表、Q2.1/Q2.2 的基础上继续开发。不会批准整个笔试提交。
- 默认 submission 检查额外逐项要求，见 delivery_requirements.json。完整全入口必须成功；缺题、材料或外部核验不足时不能通过。加分题不抵消必答缺项。
- 退出 0 表示指定范围证据通过；1 表示已有范围证据失败或失效；2 表示已有范围通过但完整交付仍有缺项。
- 相同 requirements 的历史安装证明只证明依赖曾在记录环境中安装成功；当前功能必须对应当前源码。数据库生命周期证明也只在对应运行时代码未变时复用。
- 各轮门槛实验仍保留自己的范围。源码或锁定依赖变化后，旧“通过”不可直接沿用。机器检查不替代人工审阅、候选人理解、公开 Fork 访问和最终版本核验。

## Q2.3 最小独立增量（整合待验收）

`python q2_sql_analysis/q2_3.py` 下载后的九表重新导入再查询；已有 ready 批次可用 `--skip-load`。`python run_all.py --stage q2.3` 接通本题与产物清单。预定标准见 q2_sql_analysis/ACCEPTANCE_Q2_3.md，决策及面试追问见 Q2_3_DECISIONS.md，当前实际结果见 reports/q2_3/。

默认 Q2/full 入口尚未整合本题，因此标记 not_integrated，Q2 仍为 partial。delivery_requirements.json 的 Q2.3 pending 指完整交付尚未验收，不能将单题 SQL/CLI 的完成解释为全入口已完成。源码变化已使前轮 release 报告失效；下一轮需扩展统一门槛后重跑，不沿用旧 passed。

本轮按下单时间选 2017，GMV 仅 delivered 且含运费，客户按 customer_unique_id；取消率和延迟率分母不同，见 JSON 诊断与 findings。评价选择是治理假设，尚无业务方认证。SQL 存在明显性能改进空间，此轮不声称完成查询优化。
