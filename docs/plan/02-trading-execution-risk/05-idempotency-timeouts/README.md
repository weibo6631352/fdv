# 05 幂等、超时和执行器隔离任务

## 覆盖范围

- 设计文档 `1.7 高性能与交易优先级设计`
- 设计文档 `2.8 Order Executor`
- 设计文档 `3.10 高优先级交易事件处理流程`

## Worker 任务

- 为订单 intent、outbox event、提交请求和 cancel / replace 操作定义幂等键。
- 幂等检查优先使用内存中的短临界区结构，不能为了幂等性在 P0 路径执行慢数据库查询。
- 为订单签名、HTTP 提交、cancel 请求、outbox 快路径、锁等待和执行器排队设置明确超时。
- 记录 `executor_queue_wait_ms`、`order_signed_at`、`order_submitted_at`、`order_ack_at`、提交耗时和 ACK 耗时。
- 将 P0 `trading_thread_pool` 与 P2 / P3 维护线程池、进程池隔离。
- 对超时、unknown result、重复事件和重试上限提供结构化状态，交给 reconcile 校准。

## 交付物

- 幂等键格式和生命周期说明。
- 超时配置项清单：`ORDER_SUBMIT_TIMEOUT_MS`、`ORDER_SIGN_TIMEOUT_MS`、`CRITICAL_LOCK_TIMEOUT_MS` 等。
- P0 执行器隔离策略和指标埋点清单。

## 并行接口

- 需要与 `03-realtime-runtime/04-event-bus-priority-queues` 对齐队列容量和优先级。
- 需要与 `06-observability-docs/02-metrics-alerts` 对齐指标名称和告警阈值。
- 需要与 `04-infra-persistence/03-outbox-local-queue` 对齐 outbox 幂等键。

## 注释要求

对 P0 不查数据库、短临界区、超时后进入 reconcile、执行器隔离和重复事件处理写中文注释。开发阶段不要求补充或运行验证测试。

