# 题目要求、证据与尚未证明的能力

审查依据为根 README 与招聘邮件，实际运行版本见 [当前入口](CURRENT_ACCEPTANCE.md)。本表将题目必交内容、实现采用的业务假设和额外工程实验分开。passed 指指定输入/环境/断言下的结果，不是“全部正确”的认证。

| 原始要求 | 实现及验收依据 | 证据位置 | 限制 / 后续动作 |
|---|---|---|---|
| 下载两份真实数据；从零复现 | 固定数据集版本，10 个 CSV 的大小及 SHA-256；新虚拟环境、空缓存真实下载、独立核对 | data_sources.json；reports/hardening/clean_environment_latest.json | 当前环境 Python 3.12.13 / macOS arm64；复用本机 MySQL，不是新 OS / 新服务器 |
| Python 3.10+、依赖锁定 | 实际使用满足条件的 Python 3.12；从零 pip 安装、pip check、逐项 freeze 一致 | requirements.txt；同上 | 当前 NumPy 要求 >=3.12，不声称 3.10/3.11 兼容；3.12 属题目允许版本 |
| Q1.1 类型、缺失、分布、TOP10、至少五个异常 | 独立 CSV 解析、手算边界、全量复算与错误注入 | q1_data_quality/data_quality_report.md；reports/q1_1/acceptance_latest.json | 异常是观察；业务成因不能仅由异常值认证 |
| Q1.2 前缀、商品代码、极值、匿名客户 | 冻结金额分母、代码分类与客户缺失口径；事实与推测分开 | q1_data_quality/findings.md；reports/q1_2/acceptance_latest.json；review_validation_latest.json | 非纯数字代码不必然是非商品；匿名客户群体身份、极值真实原因仍需业务核实 |
| Q1.3 三种用途、损失权衡、300–500字 | 文档长度/要点、用途差异与真实案例审查 | q1_data_quality/cleaning_strategy.md；reports/q1_3/acceptance_latest.json | 策略不是主数据确认，也不等于所有用途都应删除同一批行 |
| MySQL 8+、九表、Q2.1 | MySQL 8.4.13；九表独立行数/类型核对；缺翻译与 NULL 分开 | reports/olist_load.json；reports/q2_1/acceptance_latest.json | 真实实例实测；未用 SQLite 替代 |
| Q2.2 月订单、状态、GMV、平均配送日 | 订单/明细粒度分离；全月份独立 CSV 复算、空组/NULL/小数日手算 | q2_sql_analysis/q2_2_monthly_metrics.sql；reports/q2_2/acceptance_latest.json | GMV含运费、平均配送以有效时间订单为分母；定义写入 findings |
| Q2.3 2017 TOP20、评价去重、州内排名 | 卖家-订单粒度；确定的评价取舍；全卖家1,784行全部字段/顺序独立比较 | reports/q2_3/acceptance_latest.json；reports/q2_3_reference.json | 评价选择、并列与客户去重是明确政策，不是唯一业务答案 |
| Q2.4 三个性能问题、优化方案、统计错误 | 原 SQL、等价候选与修正统计分开；真实 EXPLAIN/计时及按州独立复算 | q2_sql_analysis/q2_4_query_optimization.md；reports/q2_4/acceptance_latest.json | 没有证明等价候选更快；原题“100倍数据五分钟”是场景，不是我们实测 |
| Q3 三输出、函数拆分、日志、断言、可复现、两分钟 | 1,067,371行；三 Parquet、原生类型回读、全量 CSV/Decimal/列表删除参考；故障输入拒绝、确定性与实际时间 | q3_etl_pipeline/pipeline.py；validation_report.md；reports/q3/acceptance_latest.json | Parquet/运行日志按原忽略规则不入库，运行后产生；性能仅限本机 |
| Q3 最近原单候选 | 时间严格在先、同客户/商品/绝对数量、确定性并列及已消费容量；候选/未知/同价/异价明确 | q3_etl_pipeline/NULLABLE_PRICE_RESULT.md；reports/q3/nullable_price_snapshot.json | 6,303个匹配是候选，不是退款事实；部分退货不自动拼单；RFM是毛购买 |
| Q4 全部低分评价、来源、结构与批处理 | 22,754行含8,309无文本、151规则、14,294模型；原始保存响应、来源行、字面引文、恢复/修复有界 | reports/q4/processing_latest.json；q4_llm_extraction/extracted_issues.json；pipeline_design.md | 客户端回执不是服务商签章；字面引文存在不能证明理解、类别、严重度、翻译准确 |
| Q4 $3预算、40分钟、费用报告 | 累计912真实请求含失败/修复；真实usage按核对时点官方费率上界1.7664627 USD；主处理977.302249秒（使用先期1,920行缓存） | q4_llm_extraction/cost_report.md；reports/q4/real_execution_milestones.json | 独立实际账单未知；不把缓存重放秒数当全新模型性能，不能声称最终源码全无缓存一次完成的耗时 |
| Q4 准确率评估方法和结果 | 30条盲标表、标签合法性/预测与标签指纹、确定的评分器、空标签拒绝 | q4_llm_extraction/accuracy_evaluation.md；evaluate_annotations.py | **未完成真人标注，准确率未评估。** 不能以AI自评代替；这是当前内容缺项 |
| Q5 800–1500字与图、SLO、容量、存储、成本、三风险 | 文档/架构图、10万与100万订单情景独立手算、交付入口 | reports/q5/acceptance_latest.json；q5_system_design/real_time_pipeline_design.md | 题目要求设计；不要求我们部署集群。SLO/成本是有参数的预算，未实测生产延迟 |
| 加分 Q6.1/Q6.2 | 原文与用户推进轮次对应；业务事实独立复算；收益是透明情景 | reports/bonus/acceptance_latest.json；bonus/ | 加分不能抵消必答缺项；收益未做因果实验 |
| 一键入口、独立运行与故障隔离 | 默认全部必答阶段、独立入口；同模块/跨模块输入失败归属；清单、运行编号、当前源码/输入/输出摘要绑定 | reports/release_execution.json；reports/release/implemented_latest.json；reports/hardening/baseline_latest.json | 本轮全入口使用完整真实模型缓存；新环境下载验证与缓存模型验证是两组实验，不能拼称同一轮全冷 |
| 每模块提交、保留历史、禁数据/密钥、中文 | 正常逐模块提交；原题三文件保留；工作树及可达历史敏感项扫描与阳性控制 | Git log；REFLECTION.md；TOOLS.md；外部候选登记 | 未 force push；历史及文件扫描覆盖指定已知隐私，不保证所有未知秘密 |
| 三份文档、完整AI原文、题号/轮次 | 文档已写；公开对话有显式隐私遮盖，本地保存未脱敏可见原文 | AI_LOG.md；ai_logs/；本地私有快照 | **公开副本不满足完整原文要求**。最终对话覆盖和提交方式仍待闭环，不擅自发布账户信息 |
| 公开Fork、邮件URL与最终hash | 已只读核实公开Fork父仓库；本轮候选留本地 | reports/release/public_fork_observation.json；SUBMISSION.md | 未推送本轮候选、未发邮件、最终公开hash未冻结；不能把旧远端当本轮发布 |
| 候选人能解释代码 | 面试决策账、实现理由、失败与取舍 | audit/DECISION_REGISTER.md；REFLECTION.md | 本人理解必须本人确认，助手不能出具通过认证 |

## 自加实验的定位

- Q2.3 的约42.3倍是**本机暖缓存、完整卖家查询**三轮实测，不是Q2.4或整体项目的加速比。冷缓存、百倍合成数据和资源峰值未认证。
- 本轮验收器损坏控制、旧版Q3不变量、断言变异，均是额外质量证据；不能由“多少项通过”推导无明显问题，更不能推导没有未知问题。
- “修改验收器后再重复付费生成全部Q4结果”是此前自加的强化实验，**原题没有要求每轮都重新付费**。当前 COLD_START 清单项仍保持未闭环；它不应被读成原题明文缺项。若后续调整门槛，须单独说明该要求的来源和现有证据，不通过改状态掩盖实际缺项。
- 原题真正要求的从零含下载运行，目前有当前源码的空环境/空缓存下载证据，以及另一次当前完整缓存入口证据；尚没有把这两者合并成“最终版本无缓存模型的一次全冷”实测。
- 独立实际账单、真人语义准确率、完整原文提交和最终公开版本仍需真实外部材料。机械重复同一已通过实验不会自动补出这些证据。

## 下一轮如何选

以尚未覆盖的风险和原始要求为依据：收到真人标签后先校验独立标注及标签/预测版本，再算指标、检查错误分布；发现真实错误才提出修复，并用未参与调整的留出样本复核。标注、账单或公开授权尚未提供时，不再次消耗模型预算、不扩大题目范围。程序或业务政策有新变动时才重跑相应独立参考和全入口，保留失败；冻结前核对源码与证据摘要、日志覆盖、公开差异及远端最终hash。

## 成本/设计两项审读缺口已修复

Q4报告生成器现包含单条与批量同口径公式、合成手算/实际用量的边界和三种分母；设计修复次数已与代码一致，正文456字。当前源码已完整回归，未重新付费调用；详见 [修复结果](Q4_COST_DOCS_RESULT.md)。本轮只关闭这两项，不填造真人准确率或实际扣款。
