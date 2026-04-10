# 02 Order Executor 任务

## 覆盖范围

- 设计文档 `2.8 Order Executor`
- 需求文档 `6. 买入逻辑`
- 需求文档 `7. 卖出逻辑`

## Worker 任务

- 保持 Order Executor 是唯一允许创建、签名、提交、取消和替换订单的模块。
- 适配 Polymarket CLOB SDK 或 REST API，但向上只暴露内部 DTO。
- 下单前写入可靠 outbox 快路径事件，包含 `trace_id` 和 intent 摘要。
- 实现订单创建、签名、提交、ACK 解析、rejected / failed 结构化原因、cancel 请求和 replace 提交。
- 执行器使用专用 P0 队列和 `trading_thread_pool`，不得与 Admin API、报表、批量 market discovery 共享线程池。
- 批量下单只允许用于明确安全的 SELL 场景；入场买入优先单笔执行。

## 交付物

- `OrderCreated`、`OrderSigned`、`OrderSubmitted`、`OrderRejected`、`OrderCancelRequested`、`OrderCancelled`、`ReplaceOrderSubmitted` 事件。
- `OrderResult` 需要区分 full fill、partial fill、no fill、live、rejected、failed、unknown / timeout。
- Polymarket BUY market order 字段语义适配：BUY `amount` 表示 USDC.e 花费金额；SELL 的数量表示 shares。

## 并行接口

- 上游只接收已通过 Risk Manager 的 intent。
- 下游输出给 Position Manager、Strategy Engine、Audit Logger、Persistence Worker。
- 与 `04-infra-persistence/03-outbox-local-queue` 对齐 outbox 快路径和失败策略。

## 注释要求

对唯一订单入口、SDK 字段语义差异、批量 SELL 限制、outbox 先写和 P0 线程池隔离写中文注释。开发阶段不运行测试。

