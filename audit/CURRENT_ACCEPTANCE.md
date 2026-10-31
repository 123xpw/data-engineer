> 本交付分支有个人目录脱敏阅读回执；它们不能用于机器验收，需实际运行重新生成。详见 [PUBLIC_EVIDENCE.md](../PUBLIC_EVIDENCE.md)。

# 当前验收入口

**Q4成本对照及设计次数两项缺口已修复并验收；当前程序范围通过，完整提交仍未闭环。按候选人决定暂不发布。**

## 本轮完整依据

- [执行前标准](ACCEPTANCE_Q4_COST_DOCS.md) 与 [修改、先红后绿、实测和限制](Q4_COST_DOCS_RESULT.md)。
- [独立账本/CSV复算及损坏拒绝](../reports/q4/cost_docs_independent.json)：912个请求、14344计费文本版本/14294模型来源行/22754低分来源行，三分母不混用；实际账单仍未知。
- [成本报告](../q4_llm_extraction/cost_report.md)：真实用量、上界分摊与合成情景分开；未进行全量单条实测，不声称测得节省。
- [5项专项](../reports/q4/cost_docs_green.json)、[108项常规套件](../reports/q4/cost_docs_units.json)、[旧接口缺失输出](../reports/q4/cost_docs_red.json)：原始文本无损封装，不以数量认证没有未知问题。Q3专项9项随完整链通过。
- [完整当前源码重放](../reports/release/q4_cost_docs_replay.json)：全模块刷新356.843秒，14294模型行缓存完整，新增请求零，账本/抽取结果/原配置未变。
- [程序范围判定](../reports/release/implemented_latest.json)：27a5fb2921e042cc9db2bd83c7b51a39，passed/implemented_ready。
- [当前完整入口](../reports/release_execution.json)：ccb9fa631c6d46bda700317e5e8d0277，passed/exit0，Q1–Q5九个必答阶段及Q2五子阶段均通过。
- [完整提交实际拒绝](../reports/release/submission_latest.json)：b93d238bda104f37b91b463c9b868611，not_ready/退出2，未替人工与外部材料放行。

## 本轮没有改动的业务与证据范围

模型提示、配置、分流/修复算法和按行缓存键未改，只有报告生成及设计叙述修正。依赖与下载机制未改；[此前新Git目录/新venv/空下载缓存同次运行](DELIVERY_REHEARSAL_RESULT.md)按未变范围引用，不冒称本轮再次执行了当前源码的新机器无缓存模型生成。

[Q3三态与旧版不变量](../q3_etl_pipeline/NULLABLE_PRICE_RESULT.md)、[Q2.3暖缓存性能及局限](../q2_sql_analysis/q2_3_performance.md)保留，本轮适用性与功能链复核通过。[前轮验收器自身审查](RELEASE_AUDIT_RESULT.md)及[要求矩阵](REQUIREMENT_EVIDENCE_MATRIX.md)说明不同实验不能合并夸大。

## 尚未闭环

真人语义标签与解盲审阅尚无；实际账单未知（Q4子README明确会查，但不要求公开账户余额）；脱敏日志与完整原文要求存在未确认例外；旧公开历史的个人信息尚未清理。最终公开Fork中的版本、远端hash、邮件及本人复核亦未完成。

最终交付终点是本人公开Fork的可访问版本和邮件中的准确hash，ZIP只是辅助快照。暂不push、不强推、不改历史、不发邮件；当前文件脱敏不能移除旧祖先历史。
