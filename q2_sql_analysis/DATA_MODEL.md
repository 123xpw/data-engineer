# Olist 最小导入模型与运行约定

本轮实际使用 MySQL 8.4.13，官方镜像固定到 mysql:8.4@sha256:a0225d1ea6631c8bc2385dc4c2faba17bbf1834ecf369e1659a9a382bd8d5dd7；实际镜像与服务器信息随运行记录保存。环境入口为 mysql_runtime.py。

## 隔离与复现

Docker 为前置软件；本项目容器名 gekko-de-exam-mysql、卷名 gekko-de-exam-mysql-data，端口仅绑定 127.0.0.1:3307。不停止或修改其他容器。脚本生成本地 .env（权限 0600，原 .gitignore 已忽略），包含随机密码；已有不完整配置不覆盖。若在沙箱内访问 Docker 失败，应区分权限与服务状态，不能静默换用 SQLite。

连接使用容器 CA 校验 TLS 证书；本地自签名证书不做主机名校验，仅用于上述回环地址，不把该设置照搬到远程生产服务。CA 保存在忽略目录 .venv/。GEKKO_MYSQL_ENV_FILE 可显式指定已有私有配置文件，干净 Python 环境验证会复用该配置和项目数据库。不要提交 .env、密码或原始 CSV。

```bash
python q2_sql_analysis/mysql_runtime.py
python q2_sql_analysis/load_olist.py
python q2_sql_analysis/q2_1.py --skip-load
python run_all.py --stage q2.1
python scripts/verify_q2_1.py
```

无 --skip-load 的 Q2.1/Q2.2 独立命令及总入口会重新导入。--stage q2 当前返回 partial/退出码 2，因 Q2.3–Q2.4 未完成；导入失败时对应查询标为 blocked_dependency，不能把旧批次查询当本次成功。Q2.2 可用 `python run_all.py --stage q2.2` 独立运行，月度诊断与证据见 reports/q2_2_validation.md。

## 原始层与分析视图

九张原始暂存表 raw_* 逐字段使用 VARCHAR(512)、utf8mb4_0900_bin；此上限针对冻结版本核验，未来超长输入必须失败而非截断。唯一物理主键是 _source_row（原始 CSV 表头后从 1 开始的逻辑记录序号）。标识符、空字符串、换行、重音与尾空格原样保留；所有参数化 INSERT 都无 IGNORE/REPLACE。

九个对应分析视图显式用 NULLIF 把空字符串映射为 NULL，原值仍可从 raw_* 取回。价格/运费/支付金额为 DECIMAL(20,3)，坐标为 DECIMAL(30,20)，整数经精确十进制校验后转换为有符号整数，时间按源格式转换且不推测时区。分类和 ID 保留字符串。无损原值往返不等于数值业务含义已确认。

验收分别比较原始层与分析层：后者使用独立声明的字段类型和 Python Decimal/datetime 转换，按来源记录核对全部字段的类型及值。日期偏移或两行金额交换可能保持行数和汇总金额，因此汇总对账不能替代逐值核验。该检查仍不决定订单状态、去重或其他业务公式。

| 表/视图 | 观察粒度和候选键 | 注意事项 |
|---|---|---|
| customers | customer_id | customer_unique_id 是跨订单客户标识，不能直接当本表主键 |
| orders | order_id | 一个订单对应一个 customer_id；状态不是全部 delivered |
| order_items | order_id + order_item_id | 订单内明细，不是订单粒度 |
| order_payments | order_id + payment_sequential | 订单可有多次支付，不可直接连明细求和 |
| order_reviews | 来源记录 | review_id、order_id 均不唯一，不能按单字段去重导入 |
| products | product_id | 类别缺失与缺英文映射不同 |
| sellers | seller_id | 销售事实来自订单明细，不能从卖家维表推断成交 |
| geolocation | 来源记录 | 邮编不唯一，完全相同行也先保留，直连客户可能大幅扩增 |
| product_category_name_translation | product_category_name | 实际唯一但查询仍用 NOT EXISTS 防重复映射影响 |

候选键在真实数据上核验，但原始层不据此丢行或施加会改变数据的业务去重。非唯一索引用于后续研究，不预先声称查询已优化；视图中的转换函数会影响索引使用，Q2.4 必须真实 EXPLAIN 再讨论。

## 发布与失败边界

导入前核验全部文件的冻结版本、哈希、表头和行数。新批次写入独立 _new_* 表；每表往返核验后才整批 RENAME 为 raw_*，再建立视图并标记 ready。调用查询前检查 _load_state。导入锁避免两个本项目导入器同时发布；成功后清理自身旧批次表。

缺输入或写入阶段失败不会发布半套新表；发布后视图阶段若失败则状态不为 ready，查询拒绝。保留的未发布暂存表可能需要人工排查，脚本不盲删它们。当前实测包括缺输入保留旧版、严格模式拒绝超长/重复键、有损转换拒绝、未就绪守卫；未做断电、强杀或并发读写故障演练，不能声称全部恢复路径已证实。

[MySQL LOAD DATA 官方说明](https://dev.mysql.com/doc/refman/8.4/en/load-data.html)指出 LOCAL 等模式可能将解释错误降为警告，因此本轮不用 LOAD DATA LOCAL 作为快捷导入；参数插入、严格模式和全字段读回共同检查保存结果。[官方排序规则说明](https://dev.mysql.com/doc/refman/8.4/en/charset-binary-collations.html)解释 NO PAD 与尾空格比较差异，本轮选择 utf8mb4_0900_bin 避免静默合并类别名。
