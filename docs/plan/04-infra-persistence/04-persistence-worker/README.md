# 04 Persistence Worker 任务

## 覆盖范围

- 设计文档 `2.12 Persistence Worker`
- 设计文档 `1.7 高性能与交易优先级设计`
- 需求文档 `11. 数据库`

## Worker 任务

- 消费 outbox，将审计事件、市场快照、订单、成交、持仓和资金分配写入 PostgreSQL。
- 数据库失败时执行可重试、可追踪处理，不阻塞交易主流程。
- 使用幂等键避免重复写入。
- Persistence Worker 属于 P3，数据库连接池必须与交易 REST / WS 连接资源隔离。
- 落库积压时优先保留交易审计事件，低优先级状态快照可以合并、降采样或延后写入。
- 暴露队列积压、写入延迟、重试次数和最后错误给 metrics / Admin。

## 交付物

- Persistence Worker 消费循环。
- 批量写入策略、重试策略和失败保留策略。
- 低优先级快照合并规则。

## 并行接口

- 上游：Outbox / Audit Logger。
- 下游：DB repository。
- 与 `03-realtime-runtime/04-event-bus-priority-queues` 对齐 P3 队列容量和降级策略。

## 注释要求

对 P3 优先级、数据库慢时交易继续、幂等写入和低优先级快照降采样写中文注释。开发阶段不运行测试。

