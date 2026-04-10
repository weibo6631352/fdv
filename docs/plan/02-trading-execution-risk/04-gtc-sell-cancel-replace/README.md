# 04 GTC SELL 与 cancel + replace 任务

## 覆盖范围

- 设计文档 `3.5 GTC 卖出流程`
- 设计文档 `3.8 Admin cancel + replace 流程`
- 需求文档 `7. 卖出逻辑`

## Worker 任务

- 买入成交后只对实际成交 NO shares 提交 `GTC SELL limit order at 0.70`。
- partial fill 后剩余未成交 SELL 继续作为 open SELL 保留。
- full fill 或 confirmed 后更新 position 和 realized PnL 相关字段。
- 实现 cancel + replace：先确认原 open SELL 已取消或已终态，再按剩余可卖 shares 提交新的 GTC SELL。
- 支持按 market / `NO token_id` 查询并操作本账户 open SELL orders。
- market 关闭、风控要求或人工操作触发时，根据配置执行 cancel、保留或 replace。
- 不提供通过 Admin API 直接创建 BUY 的路径。

## 交付物

- `SellOrderIntent`、`CancelOrderIntent`、`ReplaceOrderIntent` 编排。
- 审计事件：`exit_order_submitted`、`order_cancel_requested`、`order_cancelled`、`replace_order_submitted`。
- SELL 覆盖检查字段：持仓 shares、open SELL shares、可卖 shares、差额处理原因。

## 并行接口

- 上游：FAK BUY 流程、Position Manager、Admin API、Reconciler。
- 下游：Order Executor、Audit Logger、Persistence Worker。
- 与 `05-admin-ops/02-admin-cancel-replace` 对齐 API 输入和人工操作审计字段。

## 注释要求

对只卖实际成交 shares、cancel + replace 的先取消后提交顺序、open SELL 与持仓不一致处理写中文注释。开发阶段不要求补充或运行验证测试。

