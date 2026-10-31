# 候选版本与复现入口

> 当前脱敏候选已重建规范产物并通过程序范围验收，完整入口退出 0；完整提交仍未通过，未公开发布。见 [本轮结果](audit/PUBLIC_REPLAY_RESULT.md)。

当前已实现 Q1、Q2 四题、Q3、Q4 真实抽取、Q5 和两道加分题。Q4 真人语义评估按候选人选择稍后进行，最终材料/版本冻结与本人复核仍待闭环，**不能称整份笔试已经可提交**。原题 README、.gitignore 和数据版本清单保留不变。

## 主要成果与证据

| 范围 | 实际成果 | 证据 |
|---|---|---|
| 数据/Q1 | 版本下载、原始异常观察、用途策略、反例与独立复算 | q1_data_quality/、reports/q1_3/acceptance_latest.json |
| Q2 | MySQL 8.4.13 九表、四题、粒度修正及真实基准 | q2_sql_analysis/、reports/q2_4/acceptance_latest.json |
| Q3 | 三份 Parquet、毛购买 RFM、容量受限退货候选、全量逐行参考 | reports/q3/acceptance_latest.json |
| Q4 | 22,754 低分行：8,309 无文本、151 规则、14,294 模型；全部来源与回执 | reports/q4/processing_latest.json |
| Q5/加分 | 架构、容量/成本情景、原文复盘与业务建议 | reports/q5/、reports/bonus/ |
| 运行 | 安装/空缓存下载、生命周期修复、当前源码跨模块回归 | reports/hardening/、reports/repairs/r2/、reports/release/ |

Q2.4 等价候选没有证明比原查询更快，未伪造百倍性能。Q3 6,303 个匹配是候选，不认证真实退款；毛 RFM 不称净留存。Q5 的 SLO 与费用为设计情景，未部署压测。

Q4 累计 912 个请求含失败、试验和修复；按实际模型用量估算的费用上界 1.7664627 USD，独立实际账单尚未核验。主处理 977.302249 秒使用了先期 1920 行缓存；最终缓存重放秒数不作无缓存全量性能宣传。完整运行阶段及限制见 reports/q4/real_execution_milestones.json。

## 运行

已测 Python 3.12.13、macOS arm64、Docker/MySQL 8.4.13；锁定 NumPy 元数据要求 >=3.12，未承诺 3.10/3.11 或 Windows 兼容。原始数据与密钥不入 Git。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_all.py
```

Q4 需要本地 DEEPSEEK_API_KEY 和 Q4_LIVE=1（或 --q4-live），配置步骤见 q4_llm_extraction/RUNNING.md。没有服务时明确 partial/退出 2；失败退出 1；请求范围都执行完成才退出 0。新数据库只接收四个 MYSQL 变量，不接收模型密钥。现有数据库缺原配置不能用删卷“恢复”。

```bash
python run_all.py --stage q2
python run_all.py --stage q3
python run_all.py --stage q4
python release_check.py --scope implemented --refresh
python release_check.py
```

最后一条检查完整提交，当前仍应拒绝尚未闭环的人审/材料条件。--refresh 会重跑当前业务、独立参考、真实模型回执核验及正式全入口；使用已付费缓存防止重复费用，不能冒称再次全冷模型调用。克隆后的历史 passed 不会替代缺失产物，需要实际重跑。

## 审阅与剩余限制

先读 REFLECTION.md、TOOLS.md，再看核心实现和对应证据。AI_LOG.md 指向显式脱敏副本，完整原文要求尚未满足；业务模型原始响应本地留存，不把原始 CSV 换格式推送。代码、测试和文档主要由 Codex 协助完成，候选人理解需本人确认。

字面引文与原始回执不认证类别、否定、翻译或严重度。真人 30 条、独立账单归因、最终源码完全无缓存全冷、断电/并发发布/跨平台和本人复核仍有边界。源码与产物摘要证明版本一致，不是业务真值或独立人员认证；报告 git_base 是开始运行时的 HEAD。

公开 Fork：[123xpw/data-engineer](https://github.com/123xpw/data-engineer)，父仓库 Jay-gekko/data-engineer，候选/默认分支 codex/verified-baseline。以实际远端提交为准，最终邮件提交版本尚未冻结，后续正常追加，不 force push，也未发送邮件。
