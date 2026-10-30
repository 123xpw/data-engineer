# TOOLS.md - 工具与软件使用清单

## 交付缺陷修复所用工具（R1–R4）

- Python unittest/subprocess：在独立进程测试 -O/-OO/PYTHONOPTIMIZE、真正 CLI 退出码和故障后的文件；变异副本使用 -B 避免字节码缓存。替代是 pytest 或外部 CI，但换框架本身不会消除同源测试盲区。
- Docker/MySQL：创建本轮专属实例和卷，写入标记、删除专属容器后保留卷恢复；只清理所有权核对过的测试资源。替代为另一台专属 MySQL 测试实例，不能用 SQLite 替代题目要求。
- Python tempfile/os.replace/hashlib/contextvars：空目录产出、逐文件替换、最后发布清单和共享运行编号。替代是不可变对象存储及外部元数据事务；本项目尚未承诺并发或跨文件系统事务。
- Git 和 JSON 证据：各修复轮单独提交；保留失败记录、源码摘要和当前交付清单。替代为 CI 制品管理和签名证据；当前本地哈希不具备防恶意篡改认证能力。


## 整项目交付审查

- Git archive：从固定提交导出待审查副本，避免只在开发目录验证；替代方案为干净 clone。没有把复制源码说成全新机器。
- Python subprocess、临时目录和真实 MySQL：运行提交副本、缺输入及独立入口；在临时副本修改 SQL，比较普通与 `-O` 模式，发现断言被禁用造成误报。替代方式为隔离 CI 任务；正式业务 SQL 未被修改。
- 新的 CSV/Counter/Decimal 与 pandas 控制数脚本：从实际入口重建结果再从原始数据比较，不读取旧 passed 决定成功。替代方式为独立人员手算加另一执行引擎；本轮没有冒充独立人员审核。
- 本轮没有新增依赖、重新安装数据库、调用付费 LLM、创建公开仓库或发送邮件；外部复现与完整交付仍须后续实测。

---

## Q2.2 使用情况

- MySQL 8.4.13 与 PyMySQL：CTE 先聚合订单金额，再执行月度查询；临时表检验手算、整组 NULL、秒级精度及错误变体。替代方案是其他 MySQL 驱动；不替换题目要求的数据库。
- 标准库 CSV、Decimal、datetime：从原始文件按订单字典独立逐月复算，并量化错误连接和缺失值填零的偏差。替代方案是 pandas 独立实现；本轮避免调用生产 SQL 生成预期。
- unittest.mock 与真实子进程：前者仅检查 Q2.1 故障时 Q2.2 控制流独立，后者验证真实入口、不同工作目录和缺输入阻断；mock 结果不作为 SQL 正确证据。
- 没有新增依赖，也未宣称本轮进行了新的跨机安装、数据库性能压测或人工业务审核。

---

## Q2.1 使用情况

- Docker Desktop 与 MySQL 官方固定摘要镜像：建立独立本地实例，实际服务器为 MySQL 8.4.13；替代方案是单独安装 MySQL 8.0+。没有用 SQLite 或模拟数据库代替。Docker 初始未启动及沙箱权限问题均真实发生，已记录修复与边界。
- PyMySQL 1.1.2：参数化批量插入、流式读取、真实 SQL 与 TLS 连接，版本锁定在 requirements.txt；替代方案为 mysqlclient 或 MySQL Connector/Python。本轮不需要 SQLAlchemy，也未安装额外 cryptography，不能把模板中的工具当成已用工具。
- pandas C 解析器、标准库 CSV/Decimal：从原始文件独立检查全部数据库字段、金额与翻译缺口；替代方式为另一执行引擎与独立人员复核。不同实现仍可能共用错误的业务假设。
- MySQL 临时表与 Python 验收脚本：在真实引擎执行手算反例、严格模式错误、缺输入和未就绪守卫；替代方案是专门测试数据库。合成夹具不混入正式数据，不拿测试数量代表正确率。
- 查阅 [MySQL LOAD DATA 文档](https://dev.mysql.com/doc/refman/8.4/en/load-data.html)、[二进制排序规则说明](https://dev.mysql.com/doc/refman/8.4/en/charset-binary-collations.html)及 [PyMySQL 连接文档](https://pymysql.readthedocs.io/en/latest/modules/connections.html)：核对警告、尾空格与连接参数；替代方案是实测引擎行为并查对应版本文档。本轮也用真实反例验证关键行为。

---

## Q1.3 使用情况

- Python 标准库：文档交付、字数统计、原始 CSV 个案追踪与 Decimal 金额；替代方式是人工按相同口径核对。未为文档增加业务依赖。
- pandas：从原始文件独立核验个案，不复用探针函数生成参考值；替代方案为数据库或另一个解析器，但本轮未使用 MySQL。
- Codex：逐用途审查反例及不确定性；没有冒充独立业务审核，也没有把关键词检查当作语义证明。真实业务确认仍需数据提供方资料。

---

## Q1.2 使用情况

- pandas + Python 整数：原始字符串分组、按动态价格精度精确累计金额；替代方案为 Decimal 流式聚合或后续 MySQL DECIMAL，但此轮未使用 MySQL。
- CSV + Decimal + Counter + set：独立全量参考与口径消融，不调用生产业务函数；替代方案为另一执行引擎与独立业务复核，不能用同一个函数生成答案再自证。
- unittest、临时源码副本：手算反例、成对冲销不变性、五类定向错误注入；替代方案是其他测试框架和更广泛的生成式测试。本轮没有声称穷尽所有错误。
- 浏览工具查阅 [UCI Online Retail II 官方说明](https://archive.ics.uci.edu/dataset/502/online+retail+ii)：确认 C 前缀定义、英镑单位和线上零售背景；其他代码含义来自原始描述或明确标为未知。替代方案为向数据提供方索取数据字典，没有以第三方现成答案作为数值基准。
- 无新依赖；最新依赖仍见 requirements.txt。下方是历史轮次使用记录。

---

## Q1.1 使用情况

- pandas、numpy：原始字符串读取、有限数值统计、频次及诊断计数；没有执行业务清洗。替代方案是标准库流式聚合。
- csv、Counter、Decimal：独立参考实现，按 50 位 Decimal 精度累计和与平方和，核对 pandas 浮点统计；不调用生产统计函数。
- unittest 与临时源码副本：先核对手算样本，再植入指定错误检查测试敏感性；不能把变体捕获比例当作业务准确率。
- 依赖版本与 R0.1 一致，本轮未新增软件包。工具代码均可复现，原始 CSV 不提交。

---

## R0.1 新增实际工具

- pandas 3.1.0：使用 C 引擎独立读取真实 CSV，保留字符串及空字段，与生产端 csv.reader 的结果交叉核验；替代方案是另一个独立 CSV 引擎。
- 系统 shasum：取得固定小样本的 SHA-256，避免测试预期由生产函数生成；替代方案是其他独立摘要工具。
- Python venv/subprocess/unittest：新环境复现、真实子进程故障、测试验证器本身、临时副本变异实验；替代方案为容器和其他测试框架。
- pandas 参数依据：[官方 read_csv 文档](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html)。numpy 等间接依赖随 requirements.txt 锁定，不表示已进行业务数值分析。

---

## 已实际使用：第一轮骨架（2026-10-28）

| 工具 | 解决的问题／实际场景 | 替代方式 |
|---|---|---|
| Codex | 读取题目、分析歧义、生成骨架和测试、执行真实数据验证；原文见 AI_LOG.md | 人工实现并核验；AI 不能替代候选人的理解与人工评估 |
| Git、GitHub CLI | 克隆上游、检查变更和登录状态；尚未创建公开 Fork | Git CLI 配合 GitHub 网页 |
| Python 3.12.13、venv、pip | 隔离运行环境并锁定实际依赖 | 其他满足 Python 3.10+ 要求的隔离环境；兼容性需另测 |
| kagglehub 1.0.3 | 从题目指定 Kaggle 版本下载两份真实数据 | Kaggle CLI；手动下载只能辅助，不能代替最终自动下载逻辑 |
| Python unittest、mock、subprocess | 测试多行 CSV、损坏检测、原子写入、失败隔离及真实 CLI 的退出码 | pytest 等测试框架 |
| 浏览工具、curl | 阅读官方仓库与 Kaggle 页面，查询数据集版本元数据 | 浏览器访问同一官方来源 |

当前完整依赖版本见 requirements.txt；直接业务依赖为 kagglehub，其余为间接依赖。
CSV、SHA-256、日志及临时文件使用标准库，不为了第一轮骨架引入 pandas、数据库或 LLM SDK。
下方原模板供后续模块填写，不表示模板示例工具已经使用。

---

> 请列出本次笔试中**所有使用过的软件、工具、库**。
> 
> 📌 **填写要求**：
> - 每个工具至少写明三件事：解决什么问题、使用场景、替代方案
> - 不要为了凑数列出 `os`、`sys` 这种标准库
> - 重点列那些**对你解题有实质帮助**的工具
> - 不熟悉的工具不要硬列 —— 面试会追问

---

## 🤖 AI 工具

### 工具 1：（例如 Claude / ChatGPT / Copilot / Cursor）

- **版本/型号**：（例如 Claude Opus 4.7 / GPT-4 / GitHub Copilot ...）
- **解决了什么问题**：
- **使用场景**：
- **替代方案**：（如果不用这个 AI，你会怎么办？）

### 工具 2：

- **版本/型号**：
- **解决了什么问题**：
- **使用场景**：
- **替代方案**：

---

## 💻 IDE / 开发环境

### 工具 1：（例如 VS Code / PyCharm / Jupyter Notebook ...）

- **解决了什么问题**：
- **使用场景**：
- **替代方案**：

---

## 🐍 Python 库

### 数据处理

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| pandas | | | |
| numpy | | | |
| ... | | | |

### 数据库 / SQL（强制使用 MySQL 8.0+）

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| pymysql | | MySQL 8 驱动 | mysqlclient（需编译） |
| sqlalchemy | | 用 to_sql 灌数据 / 执行查询 | 直接用 pymysql cursor |
| cryptography | | MySQL 8 caching_sha2_password 认证 | 改 MySQL 用户改用 mysql_native_password |
| ... | | | |

### LLM / API

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| openai | | | |
| anthropic | | | |
| ... | | | |

### 其他

| 库 | 版本 | 用途 | 替代方案 |
|----|------|------|----------|
| | | | |

---

## 🛠️ 数据库工具

### 工具 1：（例如 DBeaver / DataGrip / TablePlus ...）

- **解决了什么问题**：
- **使用场景**：
- **替代方案**：

---

## 🔍 调试与分析工具

> 比如 line_profiler、memory_profiler、pytest 等

（请填写）

---

## 🌐 在线资源 / 文档

> 不需要列出每一次搜索，只列那些对你帮助最大的资源

例如：
- **Pandas 官方文档**：用于查 `merge_asof` 的精确用法（Q3.1 退货匹配）
- **MySQL 8.0 Reference Manual**：窗口函数、JSON 函数、执行计划（EXPLAIN ANALYZE）的精确语义
- **某篇博客**：（如果你参考了具体的博客，请贴链接）

---

## 📌 关键工具决策反思

> 这部分是给我们看你对工具的理解深度的

### 你做过的最重要的工具选型决策是？为什么？

例如："Q2 强制 MySQL，我在 Q2.4 优化题里对 `orders.order_purchase_timestamp` 加了组合索引并把 `LOWER(c.customer_city) LIKE '%sao%'` 改写成不依赖函数的形式，把执行时间从 X 秒降到 Y 秒"

（请填写）

### 你尝试过但**放弃**的工具/方案？

> 这能体现你的判断力

（请填写）

### 如果再做一次，你会换用什么工具？

（请填写）

## Q2.3 验证工具

MySQL 连接内临时表承载手算反例，不覆盖正式原表；替代为独立测试数据库。标准库 csv/字典/Decimal/datetime 从原始数据独立复算全部卖家，避免重用生产 SQL；替代为另一位人员使用不同工具复核，当前算法交叉验证尚不等于独立人员审核。通过 Python Decimal 计算评价选择的敏感性，不凭模型猜测业务含义。
