# 当前运行说明

提交范围和快速审阅见 [SUBMISSION.md](SUBMISSION.md)；唯一工作安排见 [PROJECT_CONTROL.md](PROJECT_CONTROL.md)。旧运行说明及各轮失败保留在 Git 历史、audit/、repairs/ 与 reports/，不作为当前范围声明。

## 环境与入口

实测 Python 3.12.13、macOS arm64、MySQL 8.4.13，依赖按 requirements.txt 安装；当前 NumPy 安装元数据要求 >=3.12。需 Docker 和可访问 Kaggle 的网络。原始 CSV 不随仓库提交，默认入口含下载及冻结版本校验。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_all.py
```

Q1–Q5 均有可执行实现，Q4 已完成真实模型处理。无模型配置时 Q4 如实 partial/退出 2；本地已配置服务和已验证回执后，本轮完整入口已实际退出 0；这不认证真人语义或最终提交材料。退出 1 表示实际失败，0 才表示请求范围均完成。已实现模块通过不抵消缺题。

各模块独立选择：--stage data、q1、q1.1、q1.2、q1.3、q2、q2.1–q2.4、q3、q4、q5。Q4 默认通过本地 .env 的 DEEPSEEK_API_KEY 与 Q4_LIVE=1 启用真实服务/缓存，未配置时不冒充完成。Q3 独立 CLI 为 `python q3_etl_pipeline/pipeline.py`，Q5 为 `python q5_system_design/design.py`。Q2 独立 CLI 可加 --skip-load 查询 ready 批次；默认会重载冻结九表。不同题目失败独立记录。

MySQL 配置/实例恢复、隔离端口与原配置复用见 [DATA_MODEL.md](q2_sql_analysis/DATA_MODEL.md)。新凭据仅用于新实例，已有卷缺配置拒绝，不删数据来伪造冷启动。TLS 设置仅用于本机回环，不能直接当远程生产配置。

## 验收

```bash
python release_check.py --scope implemented --refresh
python release_check.py --scope implemented
python release_check.py
```

先运行数据准备及正式入口。--refresh 重跑当前已有业务与正式候选；不加则核对已有报告、源码和实际文件，不能冒称重新执行。完整 submission 当前仍拒绝，原因记录在报告。

报告保存唯一编号、运行状态、源码与文件摘要；优化模式 -O/-OO/PYTHONOPTIMIZE 会被拒绝。遗留计算断言仍存在，不能关闭后说测试通过。安装证明只在依赖组合未变时复用，不能代替当前代码运行。

当前正式候选目录在本地忽略的 .venv/release-runs/，位置由 reports/release_execution.json 指明；新克隆缺少该目录应重跑，而不是相信 Git 中的 passed。Q3 输出在 outputs/，依照原 .gitignore 不提交 Parquet 和逐条日志。

## 产物与边界

正式 CLI 在空暂存目录写齐文件，最后发布各题 manifest。总入口各题共享本轮 run_id，读取时应使用 `python artifact_manifest.py --manifest <路径> --run-id <本轮编号>`，检查状态、文件集合、源码与摘要。失败后的旧文件可供调查，但不能作为本次成功；running 同样拒绝。

Q4 具体配置/预算/试运行与真人评估见 [Q4 运行说明](q4_llm_extraction/RUNNING.md)；--q4-plan 强制无网络，--offline 只约束数据下载。partial 清单普通消费者拒绝，验收器只有显式 allow_partial 才可检查其文件完整性，不能据此认定模块完成。

Q3 主实现详情见 [模块运行说明](q3_etl_pipeline/RUNNING.md)，Q2.4 的未证明提速实验见 [结果](q2_sql_analysis/Q2_4_RESULT.md)，Q5 正文为架构设计而非已部署服务。不同算法仍由同一 AI 协助编写；未知业务不被程序测试自动认证。并发发布、断电、跨平台和完全无缓存最终模型全冷仍未获全面证据。Q4 真人评估与账单归因也不由程序退出 0 自动认证。
