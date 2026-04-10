# 01 Market Discovery / Streamer 任务

## 覆盖范围

- 设计文档 `2.1 Market Streamer`
- 设计文档 `3.2 Market 发现与筛选流程`
- 需求文档 `5. 实时数据`

## Worker 任务

- 从 Gamma API 分页拉取 `active=true&closed=false` 的 events 和关联 markets。
- 处理 Market WS `new_market` 事件作为新增 market 的低延迟入口。
- 将 event / market 原始数据转换为内部 `RawMarketEvent`。
- 对分页拉取和 WS 新增事件做统一去重，优先使用 `condition_id`，其次使用 `market_slug`。
- 为发现链路生成 `trace_id`，写入 `market_discovered`，记录发现时间、来源和原始响应摘要。
- 将所有新增、更新、分页结果统一送入 Market Classifier，不绕过分类流程。
- Gamma API 拉取失败时保留已有 markets，延迟重试，不新增未知 market。

## 交付物

- Market Discovery Worker 编排。
- `MarketDiscovered`、`MarketUpdated` 事件。
- 分页、重试、去重和来源标识策略。

## 并行接口

- 依赖 `04-infra-persistence/01-polymarket-clients-schemas` 提供 Gamma client 和 raw payload 转换。
- 输出给 `01-strategy-domain/01-market-classifier`。
- 发现通过后由 `03-realtime-runtime/02-market-ws-orderbook` 和 `03-realtime-runtime/03-user-ws-position-manager` 订阅对应 token / condition。

## 注释要求

对 Gamma 分页、WS 新增、去重键选择和失败时不新增未知 market 的原因写中文注释。开发阶段不运行测试。

