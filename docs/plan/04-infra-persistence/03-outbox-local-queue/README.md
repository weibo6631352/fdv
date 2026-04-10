# 03 Outbox / Local Queue 任务

## 覆盖范围

- 设计文档 `2.11 Audit Logger`
- 设计文档 `2.12 Persistence Worker`
- 需求文档 `10. 审计日志`
- 需求文档 `11. 数据库`

## Worker 任务

- 实现本地可靠 outbox 或等价 append-only 快路径，用于交易动作先记账再异步落库。
- outbox 写入必须有短超时，数据库慢或日志慢时不得阻塞订单提交线程。
- 支持幂等键、重试次数、最后错误、事件创建时间、优先级和 raw response 摘要。
- 关键交易事件不得丢弃：订单、成交、cancel、risk failure、异常 open BUY。
- 低优先级状态快照可以合并、降采样或延后写入。
- raw response 需要长度限制和敏感信息脱敏。

## 交付物

- `OutboxEvent` 数据结构和本地队列接口。
- enqueue、ack、retry、dead-letter 或失败保留策略。
- P0 快路径和 P3 persistence 消费接口。

## 并行接口

- 上游：Order Executor、Audit Logger、Reconciler、Strategy Engine。
- 下游：Persistence Worker。
- 与 `02-trading-execution-risk/05-idempotency-timeouts` 对齐幂等键和超时配置。

## 注释要求

对先写 outbox 再异步落库、关键事件不可丢弃、低优先级快照可合并和脱敏规则写中文注释。开发阶段不运行测试。

