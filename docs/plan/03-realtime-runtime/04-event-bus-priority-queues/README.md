# 04 Event Bus / Priority Queues 任务

## 覆盖范围

- 设计文档 `1.7 高性能与交易优先级设计`
- 设计文档 `3.10 高优先级交易事件处理流程`
- 设计文档 `5.3 并发与性能开发规范`

## Worker 任务

- 实现 P0 `TradingEventQueue`，承载 orderbook price touch、订单状态、成交状态、异常 open BUY、cancel 修复和 SELL 补挂。
- 实现 P2 `MaintenanceEventQueue`，承载 market discovery、周期 reconcile、余额检查和指标聚合。
- 实现 P3 `PersistenceEventQueue`，承载数据库写入、审计 raw JSON 保存、报表快照等持久化工作。
- 所有队列必须有容量上限、优先级定义和监控指标。
- P0 队列积压时，优先丢弃、合并或限速 P2 / P3 的低价值快照事件，不能丢弃订单、成交、cancel、risk failure 等关键审计事件。
- 状态访问按 `condition_id` 或 `token_id` 分片，禁止交易路径上的全局大锁。
- P0 获取非关键锁超时时，跳过非关键读写并记录告警；关键订单状态进入 P0 修复流程。

## 交付物

- Event bus API、队列容量配置、事件优先级枚举、背压策略。
- `trading_queue_depth`、`maintenance_queue_depth`、`persistence_queue_depth`、`trading_lock_wait_ms` 指标埋点。
- 低优先级任务限速 / 暂停接口，供 Supervisor 使用。

## 并行接口

- 上游：Market WS、User WS、Strategy Worker、Reconciler、Order Executor。
- 下游：Strategy Worker、Persistence Worker、Supervisor、metrics。
- 与 `02-trading-execution-risk/05-idempotency-timeouts` 对齐 P0 执行器和锁超时配置。

## 注释要求

对队列优先级、背压、事件不可丢弃范围、分片锁和低优先级降级写中文注释。开发阶段不运行测试。

