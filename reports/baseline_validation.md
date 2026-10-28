# 第一轮验证报告（2026-10-28）

范围：数据准备与执行骨架。Q1–Q5 尚未实现。

## 骨架测试

Python unittest：10 项通过。使用明确标注的人工夹具，不作为业务数据。

## 真实数据流程检查

| 场景 | 预期退出码 | 实际退出码 | 验证结果 |
|---|---:|---:|---|
| 真实数据离线重跑 | 0 | 0 | 通过 |
| 全流程如实报告未实现模块 | 2 | 2 | 通过 |
| 空目录离线失败 | 1 | 1 | 通过 |
| 零售输入损坏不阻断独立 Olist 校验 | 1 | 1 | 通过 |
| 仅缺 Olist 时保留零售校验成功结果 | 1 | 1 | 通过 |
| 空缓存空目录真实下载 | 0 | 0 | 通过 |

完全空缓存下载的阶段耗时（含网络和校验）：
- data.retail：70.7309 秒。
- data.olist：68.8894 秒。

上述耗时不属于 Q3 ETL 性能测试；不能据此判断是否满足两分钟的 ETL 要求。

## 数据基准

| 数据文件 | 实际记录数 |
|---|---:|
| online_retail_ii.csv | 1,067,371 |
| olist/olist_customers_dataset.csv | 99,441 |
| olist/olist_geolocation_dataset.csv | 1,000,163 |
| olist/olist_order_items_dataset.csv | 112,650 |
| olist/olist_order_payments_dataset.csv | 103,886 |
| olist/olist_order_reviews_dataset.csv | 99,224 |
| olist/olist_orders_dataset.csv | 99,441 |
| olist/olist_products_dataset.csv | 32,951 |
| olist/olist_sellers_dataset.csv | 3,095 |
| olist/product_category_name_translation.csv | 71 |

## 限制与后续

- 冷启动测试使用已安装依赖的 Python 环境，空缓存、空数据目录；不等于在全新操作系统部署成功。
- pip check 已通过；尚未进行其他操作系统或 Python 版本兼容性测试。
- 未验证 MySQL、SQL、清洗规则、ETL 性能或 LLM 的质量和费用。
- 原始 CSV 与缓存已确认被上游 .gitignore 忽略；原题和忽略规则未修改。
- 首次冷启动在沙箱内因代理权限失败，随后在获准的沙箱外通过；失败不能隐去或解释为 Kaggle 数据不存在。
- 校验值由首次下载计算，不是官方签名；其用途是固定后续输入版本。
- 所有缺失和损坏场景均在临时目录中执行，不修改正式原始数据。
