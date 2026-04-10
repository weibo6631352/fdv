# 03 FAK BUY 流程任务

## 覆盖范围

- 设计文档 `3.4 FAK 买入流程`
- 需求文档 `6. 买入逻辑`
- 设计文档 `3.10 高优先级交易事件处理流程`

## Worker 任务

- 只允许提交 `BUY NO token_id` 的 `FAK` 订单，`price=0.60`，`post_only=false`。
- 订单金额来自 `target_notional_usdc`，并受 `max_order_usdc`、orderbook ask 侧可成交深度、available USDC.e 和 `min_order_size` 限制。
- 签名与提交必须走专用 P0 执行器，不等待数据库、Admin 查询、指标聚合或低优先级锁。
- full fill 后立即进入 GTC SELL 流程。
- partial fill 只对实际成交 shares 进入 GTC SELL 流程，未成交资金释放并触发再分配。
- no fill 释放全部预算并记录 `order_no_fill`。
- rejected / failed 按 `order_retry_limit` 控制重试，不无限重试。
- 订单异常进入 `live` 或本地发现 open BUY 时，立即 cancel，暂停该 market 或触发修复事件，并记录异常审计。

## 交付物

- FAK BUY 编排服务或清晰的应用层函数。
- 完整审计事件链：`order_created`、`order_signed`、`order_submitted`、`order_matched`、`order_partially_filled`、`order_no_fill`、`resting_buy_detected`、`order_cancel_requested`。
- 与 Portfolio Allocator 的资金释放事件对接。

## 并行接口

- 依赖 Strategy Engine 生成 `BuyOrderIntent`，Risk Manager 放行后调用 Order Executor。
- 输出给 GTC SELL worker、Position Manager、Audit Logger 和 Portfolio Allocator。
- 与 `03-realtime-runtime/04-event-bus-priority-queues` 对齐 P0 事件优先级。

## 注释要求

对为什么只用 FAK、为什么禁止 resting BUY、partial/no fill 资金释放和异常 live 订单处理写中文注释。开发阶段不运行测试。

