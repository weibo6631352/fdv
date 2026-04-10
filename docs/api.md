# Admin API 说明

Admin API 是人工查询和受控操作入口，不是交易策略入口。它可以暴露状态、触发人工修复动作，但不能绕过 Strategy Engine、Risk Manager 或 Order Executor。

## 设计定位

- 面向运维人员和开发人员查询系统状态。
- 支持少量明确受控的人工操作，例如暂停 market、取消 open SELL、执行 cancel + replace。
- 只读取快照、仓储数据或应用服务返回的只读视图，不能长时间持有交易热状态锁。

## 允许接口类别

| 类别 | 示例 | 约束 |
| --- | --- | --- |
| 健康检查 | `GET /health` | 不访问慢外部依赖，返回进程基本状态 |
| markets 查询 | target / eligible markets | 分页，读取快照，不阻塞 Market Registry 写入 |
| orders 查询 | open SELL、历史 orders | 优先查询仓储或 position 快照 |
| portfolio 查询 | 预算、exposure、剩余可买额度 | 不在 HTTP handler 内重新计算复杂分配 |
| 人工操作 | pause / resume、cancel SELL、replace SELL | 必须调用 app service，并进入审计链路 |

## 禁止接口类别

- 直接创建 FAK BUY 的 HTTP endpoint。
- 绕过 Risk Manager 的订单提交、取消或替换。
- 在 handler 中直接调用 Polymarket SDK。
- 在 handler 中直接写 Market Registry、Position State 或 Orderbook Cache。
- 无分页的大查询、历史全表扫描、同步导出报表。
- 与 Order Executor 共享 P0 交易线程池的后台操作。

## 调用链约定

推荐调用链：

```text
api route -> app service -> domain rule / runtime snapshot / infra repository
```

订单相关人工操作必须走：

```text
api route -> AdminService -> TradingService -> RiskManager -> OrderExecutor
```

路由层只做：
- 参数校验。
- 身份和权限检查。
- 调用应用服务。
- 返回序列化结果。

路由层不做：
- 交易判断。
- 风控判断。
- payload 签名。
- 数据库事务编排。
- WebSocket 状态修复。

## 新增接口交接清单

新增 Admin API 时，需要在 PR 中写明：
- 是否读交易热状态。如果是，读取的是快照还是需要锁。
- 是否可能触发订单动作。如果是，审计事件名是什么。
- 是否分页、限流和设置超时。
- 是否依赖数据库、Polymarket API 或慢外部服务。
- 失败时是否影响自动交易。

