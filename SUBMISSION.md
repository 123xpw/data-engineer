> 本交付分支有个人目录脱敏阅读回执；它们不能用于机器验收，需实际运行重新生成。详见 [PUBLIC_EVIDENCE.md](PUBLIC_EVIDENCE.md)。

# 候选版本与复现入口

最终交付应是本人公开Fork中的版本、可访问URL和邮件中的准确commit hash。当前按候选人决定暂不发布；本地ZIP仅是辅助快照。当前程序验证及剩余项统一见 [验收入口](audit/CURRENT_ACCEPTANCE.md)，不要把历史passed当作新克隆的运行结果。

## 运行条件与入口

实测Python3.12.13、macOS arm64、Docker/MySQL8.4.13；Python3.12满足原题3.10+，但锁定NumPy要求至少3.12，不承诺3.10/3.11或Windows兼容。首次运行需Docker已启动、可访问Kaggle，并在本地.env配置DEEPSEEK_API_KEY和Q4_LIVE=1；保留已有MYSQL配置。详细步骤见 [RUNNING.md](RUNNING.md) 和 [Q4配置](q4_llm_extraction/RUNNING.md)。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run_all.py
```

默认入口包含两份数据下载/冻结校验和Q1–Q5。退出0表示请求范围执行完成，1为失败，2为partial；没有模型服务时明确partial。各题可用--stage独立运行，Q3与Q5另有模块CLI，不因Q1失败就跳过所有题。

新克隆不含我们的私有模型缓存，真实调用有费用。缓存只有原文、提示和服务配置版本一致才复用，账本跨轮累计，不删账本或换目录来重置预算。仅新MySQL实例可生成新凭据，旧卷缺配置拒绝，不删卷伪造恢复；模型密钥不传入数据库容器。

## 原题产出与证据

| 范围 | 交付与验证入口 | 必须保留的解释 |
|---|---|---|
| 数据/Q1 | download_data.py、data_sources.json；q1_data_quality/报告/代码/用途策略 | 冻结输入、独立复算和反例；异常与业务成因分开 |
| Q2四题 | MySQL九表、四份SQL/分析；reports/q2_1至q2_4 | 订单粒度、运费、NULL、评价取舍与排名均明确 |
| Q3 | pipeline.py、三Parquet/日志运行生成、validation_report.md | 毛购买RFM、容量受限精确数量候选；报告按输出行数计空值率并解释分布 |
| Q4 | 六份指定代码/提示/结果/设计/费用/评估文件 | 真实模型来源与字面引文已核验；费用上界、真人语义和实际账单分开 |
| Q5 | real_time_pipeline_design.md、图和情景计算 | 架构设计交付，不冒称部署/SLO压测 |
| 加分题 | 原文复盘与三条业务建议 | 用户Prompt轮次不混助手更新数；收益是显式情景 |

原始数据不入Git；Q3 Parquet和逐条日志也按原.gitignore排除，由运行复现。源码包有指定个人信息脱敏检查；部分历史回执是有标记的阅读副本，接收方应重新运行生成自己的证据。源码/产物摘要认证版本一致，不认证业务真值或独立人员审核。

## 关键结果及测量边界

- Retail共1067371来源行；当前政策得到1037021销售明细、5852客户、19494取消，6303个原单候选。未匹配价差NULL不是同价；其余已比较行为6086同价、217异价。候选不等于真实退款，毛RFM不等于净留存。
- Q2.3本机暖缓存完整1784卖家查询三轮中位99.875974→2.360676秒，字段和顺序一致；不是Q2.4或整条pipeline加速。Q2.4等价候选未证明更快，修正统计不能直接算纯性能收益。
- Q4低分22754行：8309无文本、151规则、14294模型；累计912请求含试验/失败/修复，上界1.7664627USD。实际账单未核。单条/批量公式与合成对照不冒充未做的全量单条实测。
- 主模型处理977.302249秒使用先期1920行缓存；约六秒的恢复不是无缓存推理性能。新环境/空缓存数据下载和当前完整缓存入口各有实际回执，只按未变范围复用，不拼称最终源码新机器/模型全冷。

## 复核方法

```bash
python release_check.py --scope implemented --refresh
python release_check.py --scope implemented
python release_check.py
```

--refresh重跑当前功能参考和完整入口；不加则只消费现有证据。新克隆没有本地Parquet、候选目录或模型响应时，应实际重跑，不能仅凭Git中旧报告放行。完整submission门槛仍拒绝人工、材料和发布未闭环项；它混合内部证据控制与原题条款，应结合逐项矩阵理解，不把自加重复付费全冷要求冒充原题明文。

## 明确未完成与提交状态

真人30条盲标及解盲审阅未完成，准确率未知；实际账单未独立核验（Q4子README明确会查），但不要求公开余额、身份或密钥。REFLECTION/TOOLS/AI_LOG如实披露AI参与，候选人理解仍需本人复核。

AI日志按本人选择仅交付脱敏副本，未满足完整未删改原文字面要求，面试方尚未确认例外。旧公开Git历史含个人信息，当前文件脱敏不能清除祖先；不擅自改写、强推、删除或变更可见性。

本人公开Fork为 [123xpw/data-engineer](https://github.com/123xpw/data-engineer)，父仓库Jay-gekko/data-engineer。远端仍是旧版本；本地交付分支codex/delivery-redacted尚未新发布，最终公开hash和提交邮件未冻结。待隐私边界确认后再按正常提交推送并独立核对远端，不把本地包或本地hash当作已经交付。
