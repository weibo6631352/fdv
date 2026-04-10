# 03 User WS / Position Manager 任务

## 覆盖范围

- 设计文档 `2.9 Position Manager`
- 设计文档 `3.5 GTC 卖出流程`
- 需求文档 `5. 实时数据`

## Worker 任务

- User Channel 按 `condition_id` 订阅，而不是按 token id。
- 处理 user WS `order`、`trade`、fill、cancel、position 相关事件。
- 同步账户余额、USDC.e、outcome token 持仓、open orders、fills 和 trade confirmation。
- trade 状态按 `MATCHED -> MINED -> CONFIRMED` 以及 `RETRYING` / `FAILED` 处理。
- 成交未确认时可以更新风险占用，最终收益统计以 confirmed 状态为准。
- 维护每个 market 的已成交仓位、open SELL orders、open BUY 异常标记。
- 发现 open SELL orders 与实际持仓不一致时，生成 reconcile 事件。
- User WS 断线后暂停新买入，重连并完成订单/持仓 reconcile 后恢复。

## 交付物

- `BalanceUpdated`、`PositionUpdated`、`OrderStateUpdated`、`FillRecorded` 事件。
- Position 快照结构：持仓 shares、成本、open SELL 覆盖数量、pending BUY、确认状态。
- User WS 重连恢复流程。

## 并行接口

- 上游依赖 Polymarket user WS / Data API / CLOB open orders / fills。
- 下游输出给 Strategy Engine、Portfolio Allocator、Risk Manager、Reconciler、Admin API。
- 与 `02-trading-execution-risk/04-gtc-sell-cancel-replace` 对齐 SELL 覆盖字段。

## 注释要求

对按 condition id 订阅、trade confirmation 状态、未确认成交的风险占用和断线暂停新买入写中文注释。开发阶段不要求补充或运行验证测试。

