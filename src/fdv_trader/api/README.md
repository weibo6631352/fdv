# api 目录说明

该目录存放 FastAPI Admin API。Admin API 是人工查询和受控操作入口，不是策略计算和订单执行入口。

## 职责

- 暴露健康检查和运行状态。
- 查询 target markets、eligible markets、orderbook 快照、持仓、open orders 和组合分配。
- 触发受控人工操作，例如暂停 market、恢复 market、取消 open SELL、执行 cancel + replace。
- 做 HTTP 参数校验、认证授权和响应序列化。

## 允许依赖

- `fdv_trader.app` 中的应用服务。
- `fdv_trader.config` 中的只读配置。
- `fdv_trader.observability` 中的 trace / metrics 基础能力。
- FastAPI / Pydantic 等接口层工具。

## 禁止依赖与禁止行为

- 不直接调用 `infra.polymarket` 或 Polymarket SDK。
- 不直接创建、签名、提交、取消订单。
- 不直接写 Market Registry、Orderbook Cache、Position State。
- 不在 HTTP handler 中执行慢数据库全表扫描或报表生成。
- 不绕过 Risk Manager 暴露 FAK BUY 入口。
- 不与 Order Executor 共用 P0 交易线程池。

## 接口调用链

推荐：

```text
route -> app service -> domain / runtime snapshot / repository
```

订单相关人工操作：

```text
route -> AdminService -> TradingService -> RiskManager -> OrderExecutor
```

## 新增路由交接清单

新增 route 前确认：
- 是否分页、限流和设置超时。
- 是否只读。如果不是，只能触发受控应用服务动作。
- 是否需要审计事件。
- 是否可能读取交易热状态。如果会，必须使用快照。
- 是否会影响 P0 交易链路。

