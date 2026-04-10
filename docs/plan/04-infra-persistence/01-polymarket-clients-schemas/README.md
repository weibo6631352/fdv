# 01 Polymarket Clients 与 Schemas 任务

## 覆盖范围

- 设计文档 `1.2 推荐技术栈`
- 设计文档 `2.1 Market Streamer`
- 设计文档 `2.4 Orderbook Watcher`
- 设计文档 `2.8 Order Executor`
- 设计文档 `2.9 Position Manager`

## Worker 任务

- 实现或补齐 Gamma API client：events / markets 分页、active / closed 过滤、按 tag / slug 查询能力。
- 实现或补齐 CLOB client：orderbook 快照、open orders、fills、创建订单、取消订单、价格 / tick size 相关响应解析。
- 实现或补齐 Data API client：positions、trades、用户持仓和成交数据。
- 实现或补齐 Market WS / User WS client，支持重连钩子、订阅参数和消息类型解析。
- 为 Market Channel 支持 `custom_feature_enabled: true`，以接收 `best_bid_ask`、`new_market`、`market_resolved`。
- 将 Polymarket raw payload 转换为内部 DTO，不把 SDK 对象泄漏到 domain / app。
- 统一错误类型、限速响应、超时、认证失败、地理限制、余额/allowance 查询失败的结构化返回。

## 交付物

- `gamma_client.py`、`clob_client.py`、`data_client.py`、`ws_client.py`、`schemas.py` 的清晰职责边界。
- raw payload 到内部 DTO 的转换函数。
- 外部字段语义说明，特别是 BUY `amount` 表示 USDC.e 花费金额、SELL 数量表示 shares。

## 并行接口

- 上游使用者：Market Discovery、Orderbook Watcher、Order Executor、Position Manager、Reconciler。
- 下游依赖：配置与认证模块。
- 与 `01-strategy-domain/05-domain-dto-events` 对齐 DTO 字段名。

## 注释要求

对 Polymarket API 字段差异、WS 订阅参数、错误归一化和 raw payload 转 DTO 的原因写中文注释。开发阶段不运行测试。

