# 01 Audit / Trace 任务

## 覆盖范围

- 设计文档 `2.11 Audit Logger`
- 需求文档 `10. 审计日志`
- 设计文档 `3.2` 到 `3.8` 的流程审计点

## Worker 任务

- 为 market discovery 到订单操作完成的每条链路生成并传播 `trace_id`。
- 统一审计事件字段：`trace_id`、`event_id`、`event_title`、`market_slug`、`condition_id`、`token_id`、`outcome`、`side`、`order_type`、`price`、`size`、`notional_usdc`、`order_id`、`trade_id`、`tx_hash`、`status`、`reason`、`raw_response`、`created_at`、`updated_at`。
- 覆盖事件类型：market discovery、分类通过/拒绝、orderbook、entry signal、risk pass/fail、order create/sign/submit、matched、no fill、partial fill、exit submit、cancel、replace、trade mined/confirmed、error、retry、skipped。
- 交易动作先写可靠 outbox，再异步落库。
- raw response 做长度限制和敏感信息脱敏。
- 对错误、跳过、重试同样记录完整原因。

## 交付物

- Audit event schema 和 trace 传播规范。
- 事件名枚举和字段必填规则。
- 与 outbox / persistence 的写入契约。

## 并行接口

- 上游：所有项目组。
- 下游：Outbox、Persistence Worker、Admin API、metrics。
- 与 `01-strategy-domain/05-domain-dto-events` 对齐领域事件字段。

## 注释要求

对 trace 传播、交易动作先写 outbox、raw response 脱敏和 skipped / retry 审计价值写中文注释。开发阶段不运行测试。

