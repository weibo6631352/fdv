# 02 Metrics / Alerts 任务

## 覆盖范围

- 设计文档 `1.7 高性能与交易优先级设计`
- 设计文档 `3.10 高优先级交易事件处理流程`
- 设计文档 `4.4 测试重点` 中的性能指标

## Worker 任务

- 记录关键时间点：`orderbook_event_received_at`、`entry_signal_at`、`risk_passed_at`、`order_signed_at`、`order_submitted_at`、`order_ack_at`。
- 监控 `entry_signal_to_submit_ms`、`ws_event_lag_ms`、`trading_queue_depth`、`trading_lock_wait_ms`、`executor_queue_wait_ms`。
- 监控队列容量、P0 / P2 / P3 积压、outbox 积压、Persistence Worker 重试次数和最后错误。
- 监控 WS 连接状态、最近 reconcile 时间、自动下单开关状态、余额/allowance 告警。
- 当交易队列等待、锁等待或订单提交延迟超过阈值时，触发告警并请求 Supervisor 暂停低优先级任务。
- 指标采集不得阻塞 P0 交易路径。

## 交付物

- metrics 名称、类型、标签和单位表。
- 告警阈值配置项清单。
- Supervisor 降级触发接口。

## 并行接口

- 上游：Event Bus、Order Executor、WS workers、Reconciler、Persistence Worker、Admin API。
- 下游：Supervisor、Admin 查询、runbook。
- 与 `04-infra-persistence/05-config-secrets` 对齐阈值配置名。

## 注释要求

对延迟指标含义、P0 指标非阻塞采集、告警触发低优先级限速写中文注释。开发阶段不要求补充或运行验证测试。

