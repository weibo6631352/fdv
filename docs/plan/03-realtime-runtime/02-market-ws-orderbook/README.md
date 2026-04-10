# 02 Market WS / Orderbook 任务

## 覆盖范围

- 设计文档 `2.4 Orderbook Watcher`
- 设计文档 `3.3 Orderbook 监听与入场信号流程`
- 设计文档 `3.10 高优先级交易事件处理流程`

## Worker 任务

- 按 `NO token_id` 订阅 CLOB Market Channel。
- 订阅时开启 `custom_feature_enabled: true`，接收 `best_bid_ask`、`new_market`、`market_resolved`。
- 处理 `book`、`price_change`、`best_bid_ask`、`tick_size_change`、`last_trade_price`、`market_resolved`。
- 维护本地 orderbook cache、best bid/ask、spread、可成交深度和快照时间。
- 只对 `NO token_id` 的 ask 侧计算买入可成交深度。
- 当首次满足 `NO best ask <= 0.60` 时立即投递 `EntryPriceTouched` 到 P0 队列。
- `tick_size_change` 必须更新 Market Registry。
- 发现序列缺失或重连后，必须用 CLOB REST 快照覆盖本地 orderbook。
- 高频 price change 可以按 market 合并非关键快照，但首次价格触发事件不得丢失。

## 交付物

- `OrderbookSnapshotUpdated`、`EntryPriceTouched`、`MarketResolvedOrDisabled` 事件。
- orderbook 热缓存和 REST 快照覆盖策略。
- WS 断线指数退避重连策略。

## 并行接口

- 依赖 Polymarket WS client 和 CLOB REST 快照 client。
- 输出给 Strategy Engine、Portfolio Allocator、Risk Manager、Reconciler。
- 与 Event Bus 任务对齐 P0 队列投递 API，不同步写数据库或阻塞日志落盘。

## 注释要求

对 `NO` ask 侧深度、首次穿越信号、非关键快照合并、REST 覆盖和禁止同步持久化写中文注释。开发阶段不运行测试。

