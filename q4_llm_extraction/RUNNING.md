# Q4 运行与验收

当前真实结果覆盖 22,754 条低分来源行：8,309 条无文本、151 条短语规则、14,294 条模型结果。所有模型结果均有来源及回执，真人语义准确率尚未评估。

## 配置与正式入口

使用 Python 3.12，安装根目录 requirements.txt。现有 .env 中追加 DEEPSEEK_API_KEY，保留 MySQL 配置；不要把密钥发到聊天或 Git。专用密钥仅发送至 api.deepseek.com。运行前核对 deepseek_config.json 的模型与官方费率。已测 deepseek-flash 非思考 JSON 模式，批 16、最多四路，输出上限 3072。

```bash
python q4_llm_extraction/extract_reviews.py --live --limit 4 --budget 0.5
python q4_llm_extraction/extract_reviews.py --live --budget 3 --workers 4
```

默认 run_all.py 通过本地 .env 的 Q4_LIVE=1 启用真实流程，也可显式使用 --q4-live；Q4_CONFIG 可指定配置绝对路径。已验证结果按行复用，重复运行不会重新生成同一版本。默认配置由官方资料核对，价格和账号可用模型仍须在真实调用前确认。

```bash
python run_all.py --stage q4
python run_all.py --stage q4 --q4-plan
```

--q4-plan 强制无网络并如实输出 partial；验收器将它放在隔离目录，不覆盖正式模型结果。--offline 只约束 Kaggle 下载，不能替代 --q4-plan。

## 失败、预算与时间

共享累计账本 .venv/q4_state/ledger.json 覆盖所有试验和失败，不得删除或换目录重置。请求前按完整上下文上界预留；结束后以真实 usage 和峰时缓存未命中价折算费用上界，未报告用量保留预留。未知计费不自动重发，禁止把超时当免费。

先严格验证整批来源 ID，再逐行挽救有效记录。只对唯一大小写等价区间恢复原文字面，保存原引文/偏移；词语、重音、标点或歧义不自动修补。失败行最多经过主批、批四修复、单条隔离三个生成阶段，仍不合格就保留 pending。原始响应不覆盖。

每次 pipeline 执行上限 2400 秒，包含本次修复；跨轮研发/暂停的墙钟跨度另外记录，不能当作生产耗时。初版将两者混为一谈，已在契约和 Git 记录更正。主处理实测 977.302249 秒，使用 1920 条先期缓存；这不是最终源码完全无缓存全量的计时认证。最终缓存重放约六秒也不作模型性能宣传。

本轮 912 次真实请求共 1,220,873 输入 token、1,166,834 输出 token；累计费用上界 1.7664627 USD。独立实际账单未核验，费用上界不能冒称实际扣款。见 cost_report.md。

## 验收和人工边界

```bash
python scripts/verify_q4.py
python scripts/verify_q4_live.py --output-dir q4_llm_extraction
python q4_llm_extraction/evaluate_annotations.py --labels .venv/q4_labels.json
```

R1 检查合成反例、预算/恢复/并发、变异与全量无网络分流。真实处理检查以另一 CSV 解析器核对每行标识、引文、原始响应、用量与费用，不以 resolved 或 confidence 自证。两种验证仍由同一 AI 编写，不是独立人员审查。

按 accuracy_evaluation.md 填写 30 条真人盲标；候选人已说明尚未填写，当前提供本地盲标表，尚无准确率结果。引文存在不认证类别、否定、翻译或归责。空标签拒绝评估，不能由 AI 代填“人工真值”。程序执行完成与完整笔试可提交分开判定。

官方参考：[价格](https://api-docs.deepseek.com/quick_start/pricing/)、[接口](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)、[模型元数据](https://api-docs.deepseek.com/api/list-models/)。模型别名可能更新，接口回执与输入/提示版本一同保存。当前使用 macOS/Linux 的 fcntl 锁，未声称 Windows 兼容。
