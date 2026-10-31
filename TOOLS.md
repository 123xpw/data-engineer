# 工具与软件使用清单

这里只列实际使用；版本以 requirements.txt 和机器报告为准。代码、测试和文档主要由 Codex 协助编写，AI_LOG.md 指向明确标记的公开脱敏副本；完整可见原文仅本地保留。Q4 使用 DeepSeek 官方 API，912 次请求包含失败、试验和修复。

| 工具 | 解决的问题与实际场景 | 替代方案及取舍 |
|---|---|---|
| Codex 桌面应用与终端 | 分解题目、生成实现、提出并执行反例、修复、维护提交和可见对话原文 | 人工实现或其他 AI；换模型本身不会消除同源思维盲区 |
| Python 3.12.13 | 所有运行入口、数据解析、验证与 ETL；本机实际复现环境 | 题目允许更高于 3.10 的 Python；当前锁定 NumPy 元数据要求 >=3.12，不承诺 3.10/3.11 可安装整套组合 |
| Kagglehub 与锁定依赖 | 下载指定 Kaggle 版本、空缓存下载验证 | Kaggle CLI 或人工下载；仍须核对同一版本/文件哈希，不能换数据凑结果 |
| csv/Counter/Decimal/datetime | 独立逐记录/精确金额/日期参考；原始字段保留为字符串 | 第二个 SQL 或另一位人员复核；重复使用生产聚合函数不构成独立参考 |
| pandas 3.1.0、NumPy 2.5.4 | 类型/缺失统计、矢量化 ETL、分组和排序；未用 iterrows/apply 循环百万行 | SQL、Polars、Arrow 原生；更换引擎仍需验证类型和业务口径 |
| PyArrow 26.0.0 | 三份 Parquet 写入回读、类型与字节重跑核验；先在独立环境验证二进制轮子 | fastparquet 等，但需再验证 schema、缺失和版本兼容性 |
| MySQL 8.4.13、Docker | 强制 MySQL 的真实九表、临时表反例、TLS、受管卷生命周期 | 另一台独立 MySQL；SQLite 不能替代题目要求。本机 Docker 不等于新机器或生产系统 |
| PyMySQL 1.1.2 | 参数化导入、严格类型/警告检查、执行 SQL 与状态核对 | mysqlclient/SQLAlchemy；额外抽象不自动解决粒度和去重问题 |
| EXPLAIN JSON / ANALYZE | 区分估计计划与实际迭代器；Q2.3 三轮同口径对照，局部连接顺序预检失败后增加事实块隔离；Q2.4 保留未提速结论 | 生产回放、压测、监控；本次未完成生产或百倍规模实验，固定顺序未来可能退化 |
| unittest/subprocess | 手算固定答案、真实 CLI、运行模式、异常隔离和变异测试；旧骨架副本使用 -B，Q4 副本逐次删除字节码缓存 | pytest/外部 CI；当前仍由同一 AI 编写，不能冒称独立人员审查 |
| tempfile/os.replace/hashlib | 空目录生成、完整发布、编号和摘要校验，拒绝失败后旧结果 | 不可变对象存储与元数据事务；当前未证明并发发布/断电恢复 |
| requests/multiprocessing/fcntl | Q4 兼容接口、墙钟终止、累计账本排他锁；真实 DeepSeek 调用、原始回执与全量分流 | SDK/异步客户端；已验证服务兼容性/真实处理；独立账单与真人语义待核验，未声称 Windows 支持 |
| Git 与 gh CLI | 有意义的分模块提交、保留失败历史；核实并建立公开 Fork | GitHub UI；未 force push，也未发送提交邮件 |
| Mermaid 与 Markdown | 版本可审查的架构图、运行/反思/决策记录 | ASCII 图或绘图软件；图和字数通过不表示系统压测通过 |

Q3 用并查集跳过已消费候选，仅迭代取消子集；独立参考用列表删除与 CSV/Decimal，避免调用生产匹配函数。两者仍共享由 Q1 解释导出的业务政策，不认证商品主数据。

价格三态修复额外使用 Git 已提交的旧代码在临时目录重建同一输入，比较销售/RFM 字节和退货全部非价格状态列；用 pandas nullable boolean 与 PyArrow 原生类型/空值检查验证存储，故意改写一条真实未知值检查独立参考拒绝。没有把算法不同当作口径独立，也未把临时 Parquet 或数据集提交到 Git。

Q4 已完成真实模型抽取；真人准确率评估按用户选择稍后进行。不得将助手推理、草案、规则预查计作人工标签，也不填写无法获得账单的总 Token 花费。

## 参考的官方资料

- [MySQL 范围优化](https://dev.mysql.com/doc/refman/8.4/en/range-optimization.html)：说明 LIKE 范围条件，不能把前导通配符偷偷改成精确城市。
- [MySQL 生成列索引](https://dev.mysql.com/doc/refman/8.4/en/generated-column-index-optimizations.html)：候选表达式索引思路，未将建议冒称已获性能提升。
- [PyArrow 26.0.0](https://pypi.org/project/pyarrow/26.0.0/)：核对版本、Python 支持及平台轮子。
- [Debezium outbox](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html)：事务状态与事件一致性的设计依据。
- [ClickHouse 常见问题](https://clickhouse.com/blog/common-getting-started-issues-with-clickhouse)：物化视图、重复与数据模型边界；当前只用于设计，未部署。

- [OpenAI Chat Completions 官方参考](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)：核对 JSON mode、max_completion_tokens 与 usage；使用 OpenAI Docs 技能检索，未指定或虚构服务模型/报价。

## 使用边界

安装和空缓存下载在新虚拟环境完成，复用本机项目 MySQL 配置；没有宣称重建 OS、远程生产库或独立人员审核。依赖已锁定，不等于覆盖所有平台；推荐复现实际验证的 Python 3.12.13。原题 README/.gitignore/数据版本清单保持不变，CSV、Parquet 与私有配置未提交。

DeepSeek 参考：[模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)、[调用协议](https://api-docs.deepseek.com/api/create-chat-completion/)。已验证账号支持 deepseek-flash；使用非思考 JSON 模式。费用为核对时点官方费率计算的上界，不能代替独立实际账单。
