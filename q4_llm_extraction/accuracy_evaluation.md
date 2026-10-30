# Q4 人工评估协议与当前结果

当前结果：**未进行真人标注，尚无语义准确率**。R1 合成夹具只核验程序和手算公式，不能填入此处当人工结果。

我选择在 14,445 条非空低分来源行中，以固定种子 SHA256 排序取 30 行，不查看预测再挑样本。生成的 annotation_blind.json 只含原文和标识，不展示模型结果与路由。重复 review_id 按来源行保留。该样本不包含无文本记录，也不保证稀有类别均被抽到；不外推所有评价、所有卖家或整体准确率。

将模板复制到被忽略目录（例如 .venv/q4_labels.json），不要直接修改会被下一次运行覆盖的模板。真人先独立填写 annotator、annotated_utc，以及每行 labels：

```json
{"categories":["quality_defect"],"sentiment":"negative","actionable_for_seller":true,"note":"存在歧义时记录判断依据"}
```

类别取任务枚举，不能确认具体问题时 categories=[]。情感取 negative/neutral/positive；可行动性按“存在具体可跟进问题”，不等同确认卖家负有责任。随后解盲读取预测，填写 prediction_audit：evidence_supported、translation_faithful、severity_reasonable 三个布尔值，并在 note 记录错误。最好由懂葡语的第二人仲裁争议；机器翻译只能辅助，不能冒称另一位人工标注者。

```bash
python q4_llm_extraction/evaluate_annotations.py --labels .venv/q4_labels.json
```

程序拒绝空标签、非 30 条、来源/原文变化、重复来源、未完成预测和缺失解盲复核。输出类别集合的微平均 precision/recall/F1、整行集合 exact-match、情感（<-0.2 / >0.2 阈值）与可行动性一致率；无分母返回 null。引文语义、翻译、严重度仅在预测有问题的行上汇总人工通过率。全部逐条差异保留，不只展示成功例。

我没有把“引文逐字存在”当作语义认证：否定句可以被错误分类、英文也可能反译。30 行不能证明模型总体稳定；同一人解盲仍有锚定偏差。正式实测后需填写原始标注摘要、预测摘要、结果、错误分析和迭代前后同一样本比较，不能不断改测试集直到分数好看。
