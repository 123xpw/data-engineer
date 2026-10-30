# 候选版本说明与复现入口

本项目保留原题 README，不将题目改写为个人介绍。当前完成 Q1、Q2 四题、Q3 和 Q5 文档；Q4 模型服务按候选人选择稍后配置，尚未完成。完整提交门槛仍为 not_ready，不能将阶段通过称为整份笔试完成。

## 当前成果与证据

| 范围 | 已实际完成 | 主要证据 |
|---|---|---|
| 数据/Q1 | 版本化下载、类型/缺失/异常观察、用途策略、反例和独立复算 | q1_data_quality/ 与 reports/q1_3/acceptance_latest.json |
| Q2 | MySQL 8.4.13 九表、翻译缺口、月度、卖家、查询分析与统计修正 | q2_sql_analysis/Q2_3_RESULT.md、Q2_4_RESULT.md |
| Q3 | 三份 Parquet、毛购买 RFM、容量受限退货候选、日志、逐行独立参考与确定性 | reports/q3/acceptance_latest.json |
| Q5 | 1281 非空白正文字符、架构图、容量/费用情景与失败预案 | reports/q5/acceptance_latest.json |
| 新环境 | 空虚拟环境、无缓存安装、空缓存真实下载、实际入口 | reports/hardening/clean_environment_latest.json |

Q3 当前规则得到 1,037,021 条正向商品毛交易、5,852 位客户、19,494 条取消事件；6,303 个匹配是候选，不认证真实退款。RFM 是毛购买口径，报告公开候选退货对 1,506 位客户的潜在影响。Q2.4 的等价候选没有证明比原查询更快；保留实际结果，不伪造百倍性能。

## 从零运行

实际验证环境为 Python 3.12.13、macOS arm64、Docker/MySQL 8.4.13。锁定 NumPy 的安装元数据要求 Python >=3.12；复现请使用 3.12，不能将锁文件较宽泛的首注释当作 3.11 组合已验证的承诺。题目要求的 Python 3.10+ 允许本项目选择更高版本；未作跨平台保证。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_all.py
```

当前退出 2 明确表示 Q4 未完成；其他已实现模块执行成功不抵消该缺项。需要网络访问 Kaggle，Docker 应可用；新实例自动生成本地私有 .env，已有数据库需要原配置，见 q2_sql_analysis/DATA_MODEL.md。CSV、Parquet、日志与密钥均不入 Git；运行后生成所需文件。

```bash
python run_all.py --stage q2
python run_all.py --stage q3
python run_all.py --stage q5
python release_check.py --scope implemented --refresh
python release_check.py
```

先执行数据准备/正式入口，再运行验收。--refresh 会执行独立参考、反例、实际全入口和当前源码核对；耗时包括多轮验证，不等同于单模块生产耗时。最后一条检查完整提交，当前仍拒绝。仅检查已有报告时不加 --refresh；缺少本地生成产物或源码变化会失败。

## 审阅顺序与限制

先读 [REFLECTION.md](REFLECTION.md)、[TOOLS.md](TOOLS.md)，再看核心实现及对应机器报告。[AI_LOG.md](AI_LOG.md) 指向可见对话原文，不以摘要替代。各报告绑定文件摘要，git_base 是开始验收时的 HEAD；提交之后代码摘要不变，证据才可沿用。测试数量、文件哈希不证明业务真值，也不是独立人员审查。

Q4 未做真实模型抽取/用量核算/人工 30 条评估，不能填写假结果。Q5 延迟和年度费用为设计目标及假设情景，未部署压测。Q3 商品政策、评价选择、退货关系仍有未获业务确认的部分。并发发布、断电恢复、跨平台及完整最终版本冷启动仍需审查。

公开 Fork：https://github.com/123xpw/data-engineer ，来源 Jay-gekko/data-engineer。候选分支为 codex/verified-baseline，已推送并设为默认分支，匿名访问和代码提交一致性已核验（见 reports/github_fork_metadata.json）；以实际远端提交为准。当前尚非最终邮件提交版本，后续补齐 Q4 时仍会正常追加提交，保留历史，不 force push。
