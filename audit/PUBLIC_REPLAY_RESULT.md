# 脱敏候选：当前源码重放结果

> 本文保留 0f40889 阶段的验收快照与原始耗时；后续已采用 Q2.3 性能候选并重新回归。当前结论见 [最新验收入口](CURRENT_ACCEPTANCE.md)，旧数值不当作新版本基准。

**程序范围通过，完整提交仍未通过；本地候选尚未推送。** 验收标准先见 [本轮契约](ACCEPTANCE_PUBLIC_REPLAY.md)。

## 修改与首次失败

Q2.4 验收器提前使用尚未生成的 TLS 证书，新工作目录报 FileNotFoundError。已在手算前增加 MySQL/TLS 就绪检查。业务 SQL、金额/分母政策、模型提示和真实模型结果均未改变；脱敏只改变成本报告说明及相关文档。

- [首次失败](../reports/q2_4/acceptance_8367871e468f45c580e4c981d7804a17.json)
- [修复后当前验收](../reports/q2_4/acceptance_93eaa5402fcc430b8c8d87cd234c27ce.json)

完整可见对话仍在本地，公开副本有明确遮盖。已修正 REFLECTION、TOOLS 和加分复盘中将公开副本称为完整原文的旧说法；该材料要求继续待办。

## 实际证据

| 范围 | 结果 | 新回执 |
|---|---|---|
| Q1 链 | 通过 | [1f7b7362b1be40b6bae7f7d9e16439fd](../reports/q1_3/acceptance_1f7b7362b1be40b6bae7f7d9e16439fd.json) |
| Q2.1 | 通过 | [cc488b9ba0f9448eb0a64fb25a276978](../reports/q2_1/acceptance_cc488b9ba0f9448eb0a64fb25a276978.json) |
| Q2.2 | 通过 | [eade41906b8e44e09e9383d201104e4b](../reports/q2_2/acceptance_eade41906b8e44e09e9383d201104e4b.json) |
| Q2.3 | 通过 | [39ef2c5b9c604f738358759657584b92](../reports/q2_3/acceptance_39ef2c5b9c604f738358759657584b92.json) |
| Q2.4 | 通过 | [93eaa5402fcc430b8c8d87cd234c27ce](../reports/q2_4/acceptance_93eaa5402fcc430b8c8d87cd234c27ce.json) |
| Q3 全量独立参考 | 通过 | [f23a48f0b5df454792a7dd7e55274ff1](../reports/q3/acceptance_f23a48f0b5df454792a7dd7e55274ff1.json) |
| Q4 工程反例/恢复/变异 | 通过 | [24f5a197a50540f2949ff3db363d2355](../reports/q4/engineering_24f5a197a50540f2949ff3db363d2355.json) |
| Q4 真实保存响应/来源/费用 | 通过 | [03846031dd67484aba46282415b1bb04](../reports/q4/processing_03846031dd67484aba46282415b1bb04.json) |
| Q5 设计交付 | 通过 | [1fdb43fe312a4a79af30063613ccd784](../reports/q5/acceptance_1fdb43fe312a4a79af30063613ccd784.json) |
| 两道加分题事实复算 | 通过 | [dbbfc7bc1e3a4cbba5c78e06bf14138c](../reports/bonus/acceptance_dbbfc7bc1e3a4cbba5c78e06bf14138c.json) |
| 全模块已实现范围 | 通过 | [f2ded53b0a454621a84604733e7f3054](../reports/release/implemented_f2ded53b0a454621a84604733e7f3054.json) |

最终完整入口运行编号 `0fd9e72ffc204a67a3998a48700f3f1e`，退出码 **0**；数据、Q1 三题、Q2 四题、Q3、Q4、Q5 均为 passed。[实际入口记录](../reports/release_execution.json)。

Q4 预检 14,294 条模型文本全部命中本版本有效缓存，阻塞零；模型账本逐字不变、请求总数保持 912、无新增请求，最终模型结果逐字不变，原私有配置及账本未改动。Python 网络守卫先作阳性检查，随后重放没有外部连接尝试；进程使用模型占位凭据。实际守卫范围与各阶段退出码见 [重放回执](../reports/release/public_replay.json)。

完整程序回归及最终全入口共 1042.924 秒；这是含多次验证的验收链耗时，不能当作一次 pipeline 或模型生成耗时。最终入口 Q2 阶段 129.7068 秒，Q3 阶段 3.1225 秒，Q4 已付费缓存重放 5.937 秒。已有单元测试 91 项通过，但数量不是正确率。

依赖安装、固定 SQL 的真实基准、数据库生命周期实验在对应源文件/依赖/数据未变范围内复用，当前业务与入口重新执行；不是全新 OS、全新数据库或最终源码完全无缓存模型实测。旧报告保留历史，未回填摘要。运行开始的 git_base 为 15c17e1，适用性以源码和产物指纹判定。

## 仍不能据此声称的事情

完整提交检查按预期退出 **2**，判定 not_ready。待办仍有真人语义评估、独立实际账单、日志完整性/最终覆盖、最终全冷证明、本人复核以及最终远端/版本登记；见 [实际拒绝记录](../reports/release/submission_latest.json)。源码摘要和逐字引文不能证明类别、翻译、否定、责任、严重度或候选人理解。

Q2.3 是下一项明确的性能候选：估计计划提示较大的中间连接；只读会话观察和估计计划保留在本地。优化前必须固定口径、核对全部卖家字段，再用实际对照计时决定是否采用。当前 SQL 未改，不宣传新提速。

原题允许在 REFLECTION 中说明未完成部分；这不免除完整原文要求，也不把当前不完整条件改为已经完成。是否提交明确列出限制的版本，由候选人在确认材料要求后决定。未发送邮件。
