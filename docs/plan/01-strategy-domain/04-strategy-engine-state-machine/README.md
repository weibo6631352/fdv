# 04 策略引擎与状态机任务

## 覆盖范围

- 设计文档 `2.7 Strategy Engine`
- 设计文档 `3.3 Orderbook 监听与入场信号流程`
- 设计文档 `3.4 FAK 买入流程`
- 设计文档 `3.5 GTC 卖出流程`

## Worker 任务

- 根据 `TargetMarketAccepted`、`OrderbookSnapshotUpdated`、`EntryPriceTouched`、`AllocationPlanUpdated`、`OrderMatched`、`OrderPartiallyFilled`、`OrderNoFill`、`OrderRejected`、`PositionUpdated` 生成交易意图或跳过原因。
- 入场只允许由 `NO best ask <= 0.60` 的首次触发或必要重算触发。
- FAK BUY intent 必须记录 `target_notional_usdc`、预估 shares、`price=0.60`、`post_only=false`、`trace_id`。
- full fill / partial fill 后按实际成交 shares 生成 `GTC SELL at 0.70`。
- no fill 后释放全部预算并触发再分配。
- rejected / failed 记录原因并尊重 `order_retry_limit`，不得无限重试。
- 如果买入订单返回 `live` 或本地发现 open BUY，立即生成 cancel intent 并记录异常。

## 交付物

- `BuyOrderIntent`、`SellOrderIntent`、`CancelOrderIntent`、`ReplaceOrderIntent`、`StrategySkipped`。
- market 级状态机，覆盖候选、可买、已发买单、已成交、已挂卖单、暂停、终态。
- 对同一 market 的非关键价格刷新可合并，但订单状态、成交状态、异常 open BUY 和首次入场信号不得丢失。

## 并行接口

- 上游依赖 `Market Registry`、`Orderbook Watcher`、`Portfolio Allocator`、`Position Manager`。
- 下游输出给 `Risk Manager` 和 `Order Executor`。
- 与 `03-realtime-runtime/04-event-bus-priority-queues` 对齐 P0 事件消费方式，不能等待 Admin 查询、报表、全量 reconcile 或数据库落库。

## 注释要求

对 FAK / GTC 状态转换、no fill 资金释放、异常 open BUY 取消和非关键事件合并策略写中文注释。开发阶段不要求补充或运行验证测试。

