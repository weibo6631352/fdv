# 02 Admin cancel + replace 任务

## 覆盖范围

- 设计文档 `3.8 Admin cancel + replace 流程`
- 设计文档 `2.13 Admin API / CLI`
- 需求文档 `7. 卖出逻辑`

## Worker 任务

- Admin API 接收 market slug / condition id / `NO token_id` 和新卖出价格。
- 查询该 market 下本账户所有 open SELL orders。
- 校验目标价格符合 tick size，market 可操作，持仓数量足够。
- 逐个取消 open SELL orders。
- 确认取消成功或订单已终态。
- 按剩余可卖 shares 提交新的 GTC SELL。
- 记录 `order_cancel_requested`、`order_cancelled`、`replace_order_submitted`。
- 不提供 dry-run / paper trading 模式，不允许通过 Admin API 绕过 Risk Manager 直接下 FAK BUY。

## 交付物

- cancel + replace 应用服务入口。
- Admin 操作请求 / 响应 DTO，包含 `trace_id`、操作者、目标 market、原订单、新价格、执行状态和失败原因。
- 人工操作审计字段。

## 并行接口

- 上游：Admin API / CLI。
- 下游：Risk Manager、Order Executor、Position Manager、Audit Logger。
- 与 `02-trading-execution-risk/04-gtc-sell-cancel-replace` 对齐 SELL replace 编排。

## 注释要求

对只允许受控 SELL 操作、tick size 校验、先取消后提交和禁止绕过风控写中文注释。开发阶段不要求补充或运行验证测试。

