# 02 Market Registry 与模型任务

## 覆盖范围

- 设计文档 `2.3 Market Registry`
- 设计文档 `1.6 状态真相来源`
- 设计文档 `4.2 核心数据模型建议`

## Worker 任务

- 定义本地 target market 状态结构，包含 `event_id`、`event_title`、`event_slug`、`market_slug`、`condition_id`、`YES token_id`、`NO token_id`、`tick_size`、`min_order_size`、`neg_risk`、`category`、`tags`、`matched_keywords`、`trading_status`、`reject_reason`。
- 维护 `condition_id -> market`、`no_token_id -> market`、`slug -> market` 索引。
- 支持 market 生命周期状态：`candidate`、`eligible`、`paused`、`closed`、`resolved`、`rejected`。
- 支持 `tick_size_change`、`market_resolved`、`orderbook disabled`、人工暂停/恢复和 reconcile 覆盖状态。
- 提供只读快照接口给 Admin API、Persistence Worker、指标聚合读取，避免低优先级任务持有交易状态写锁。

## 交付物

- Market 领域模型和 registry API 契约。
- 基于 `condition_id` 或 `NO token_id` 的分片访问建议，避免全局大锁。
- 状态变更事件，例如 `TargetMarketAccepted`、`MarketStatusChanged`、`TradingPausedForMarket`。

## 并行接口

- 上游：Market Classifier、Orderbook Watcher、Reconciler、Admin API。
- 下游：Strategy Engine、Portfolio Allocator、Risk Manager、Persistence Worker。
- 与 `03-realtime-runtime/04-event-bus-priority-queues` 对齐锁超时和快照读取策略。

## 注释要求

对状态真相来源、快照读取、分片锁和生命周期转换原因写中文注释。开发阶段不要求补充或运行验证测试。

