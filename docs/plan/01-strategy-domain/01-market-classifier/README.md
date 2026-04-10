# 01 Market 分类任务

## 覆盖范围

- 设计文档 `2.2 Market Classifier`
- 设计文档 `3.2 Market 发现与筛选流程`
- 需求文档 `4. 市场筛选`

## Worker 任务

- 实现 Crypto 分类硬前置检查，Pre-Market 只能作为附加标签，不能替代 Crypto / Cryptocurrency 分类。
- 实现 FDV 命中规则：优先从 `event title` 或明确等价字段识别 `FDV` / `fully diluted valuation`。
- 实现 500M 阈值命中规则：从 `market question`、market name、`market slug` 识别 `$500M`、`500M`、`500 million` 等目标表达。
- 显式排除 `$150M`、`$300M`、`$800M`、`$1B` 等非目标阈值。
- 禁止把宽泛 `valuation` 作为独立命中条件，避免误匹配普通估值类 market。
- 不引入外部数据判断 token 上线时间、symbol 或项目背景。
- 解析并输出 `condition_id`、`YES token_id`、`NO token_id`、`tick_size`、`min_order_size`、`neg_risk`、命中字段、命中关键词和拒绝原因。

## 交付物

- `TargetMarketAccepted` / `TargetMarketRejected` 或等价领域事件。
- 结构化拒绝原因枚举，覆盖非 Crypto、非 FDV、非 500M、其他阈值、交易条件缺失、字段解析失败和 resolution 条件异常。
- 分类函数保持纯函数风格，不依赖 Polymarket SDK、数据库、FastAPI 或环境变量。

## 并行接口

- 输入由 `03-realtime-runtime/01-market-discovery-streamer` 提供 `RawMarketEvent`。
- 输出写入 `01-strategy-domain/02-market-registry-models`，并投递给 Market WS 订阅任务。
- 审计字段名需要与 `06-observability-docs/01-audit-trace` 对齐。

## 注释要求

对 Crypto 前置、FDV / 500M 匹配、非目标阈值排除和不使用外部数据的原因写中文注释。开发阶段不要求补充或运行验证测试。

