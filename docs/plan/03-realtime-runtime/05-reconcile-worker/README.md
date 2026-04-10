# 05 Reconcile Worker 任务

## 覆盖范围

- 设计文档 `2.10 Reconciler`
- 设计文档 `3.7 Reconcile 流程`
- 设计文档 `1.6 状态真相来源`

## Worker 任务

- 定时 reconcile，并在 WS 重连后立即触发校准。
- 拉取 active target markets 的 Gamma 快照，校验 active、closed、archived、enableOrderBook。
- 拉取 CLOB orderbook 快照，覆盖本地 best bid/ask 和深度。
- 拉取 open orders、fills、positions、USDC.e balance 和 allowance。
- 对比本地状态与权威快照，输出 `ReconcileDiffDetected`。
- 发现 open BUY order 必须取消。
- 发现持仓 shares 大于 open SELL shares，按差额补挂 GTC SELL。
- 发现 open SELL shares 大于持仓 shares，取消多余 SELL。
- 发现 market closed / resolved / disabled，停止新买入，并根据配置处理 open SELL。
- 批量扫描属于 P2；异常 open BUY、缺失 SELL 补挂、market 不可交易暂停等修复动作可以升级为 P1 / P0 事件。
- Reconciler 不得长时间持有 Market Registry、Position State 或 Orderbook Cache 的写锁。

## 交付物

- `ReconcileStarted`、`ReconcileDiffDetected`、`ReconcileApplied`、`TradingPausedForMarket`。
- 差异类型和修复动作映射表。
- reconcile 审计事件和 PostgreSQL 快照写入请求。

## 并行接口

- 依赖 Gamma / CLOB / Data API clients、Market Registry、Orderbook Cache、Position State。
- 输出给 Order Executor、Strategy Engine、Persistence Worker、Admin API。
- 与 `05-admin-ops/04-startup-bootstrap` 对齐首次 reconcile 完成前禁止自动下单。

## 注释要求

对权威快照覆盖、open BUY 立即取消、SELL 补挂/取消和 P2 升级 P1/P0 的条件写中文注释。开发阶段不运行测试。

