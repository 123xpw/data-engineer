# Q4 运行与验收

## 无网络验收

```bash
python run_all.py --stage q4 --q4-plan
python scripts/verify_q4.py
```

生成全部低分行的分流结果、累计指标、成本说明与 30 条盲标模板。待模型记录的字段为 null，退出 2；q4_manifest.json 为 partial，普通成功清单消费者拒绝。输出无文本行的 sentiment_score=0/confidence=0 是未知约定，不能当作证实中性。

## 配置后真实试运行

用户已选择 DeepSeek。仓库 deepseek_config.json 已根据 2026-10-30 官方文档配置 deepseek-flash、非思考模式、max_tokens 与 JSON mode；上下文上界 1,048,576，批 8/输出上界 3072。单价使用峰时缓存未命中输入 0.3 / 输出 1.2 USD 每百万 token，均作为保守上界，不将缓存折扣或非峰时折扣填成已获得。真实调用前重新核实官方价格和账号模型可用性，见下方来源。

其他服务可将 config.example.json 复制到 .venv/q4_config.json 后填写；该示例是失效占位。通用适配使用 max_completion_tokens，DeepSeek 适配使用 max_tokens 并禁用思考；不同服务不能只换 URL 就假定兼容。

在现有本地 .env 追加 DEEPSEEK_API_KEY（不要覆盖已有 MySQL 配置）。也支持专用 Q4_API_KEY 对应显式端点；DEEPSEEK_API_KEY 只用于 api.deepseek.com，OPENAI_API_KEY 只用于 api.openai.com。不要在聊天或 Git 发送密钥。

```bash
python q4_llm_extraction/extract_reviews.py --live --limit 4 --budget 0.5
```

先查看 .venv/q4_state/ledger.json 的原始 request_id/usage、原文与结果，核对服务账单、单价和语义。若超时/无 usage，不自动重试；预算预留继续占用。若过程停止，这不是“免费失败”。不要删账本或更换目录绕过费用。价格/模型/提示变更会产生新的语义版本，但费用仍累加在同一账本。

小样本、账单核对通过再扩大：

当前实现为串行小批，请先用真实服务测出每条 token 和批次时延，再估算全量所需时间。守卫能在时限停止，不能证明 14,294 条语义文本能在四十分钟内完成；若吞吐不够，需另轮验收更大批次或有界并发，不能直接把时限设置为更大值。未知模型/未测吞吐前不做完成保证。

```bash
python q4_llm_extraction/extract_reviews.py --live --budget 3
```

首次真实请求起累计墙钟限 2400 秒；中断不重置。超时不明请求需先与服务端人工对账，程序不会为凑全量重发。不同批大小按行复用成功结果；没有自动提升预算。当前支持 macOS/Linux 的 fcntl 锁，未声称 Windows 可运行。

正式默认入口可通过 --q4-live --q4-config 显式开启；或在 .env 加 Q4_LIVE=1 ，默认使用本仓库 DeepSeek 配置；Q4_CONFIG 可覆盖为本地配置绝对路径，使 python run_all.py 使用同一配置。验收脚本强制 --q4-plan，防止回归测试产生付费请求。--offline 只约束 Kaggle 下载，不替代 --q4-plan。

## 人工评估与证据边界

按 accuracy_evaluation.md 复制模板并盲标，禁止 AI 代填“人工真值”。evaluate_annotations.py 只计算已提交标签的差异，不能认证标注人身份、葡语能力或标签就是业务真理。真实全量费用、时长和语义评估未闭环时，Q4 不通过完整提交门槛。

接口字段核对来源：[OpenAI Chat Completions 官方参考](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)（2026-10-30）。这里只采用请求/用量协议，不据此虚构其他兼容服务支持情况、模型价格或本账号可用额度。

## DeepSeek 价格与协议证据

- [模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)：记录的是核对时点的峰时上界；服务报告 usage 的上界折算不是实际账单费用。actual_billed_cost_usd 在未核对账单时为 null。
- [模型元数据](https://api-docs.deepseek.com/api/list-models/)：context_window=1048576。此处预留整个上下文上界，因此小样本也预留 0.3182592 USD，实际有 usage 后改为按已用 token 的上界占用。末段余量不足仍可能保守停止，不能降低上界凑通过。
- [调用协议](https://api-docs.deepseek.com/api/create-chat-completion/) 与 [JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)：空内容即使 stop 也拒绝，按已用量计费上界，不自动重试。

账户账单可能以 CNY 计价，不能把余额变化直接当 USD；实际扣费、币种和换算依据需另存证据。共用账号还有其他消费时，余额差不能单独归因本任务。
