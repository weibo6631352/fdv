# 交易执行与风控组

## 目标

负责所有下单前门禁和订单生命周期动作。该组必须保持 Order Executor 是唯一订单入口，Risk Manager 是任何下单前的强制门禁。

## 可并行任务

| 任务 | Worker 入口 | 主要模块 |
| --- | --- | --- |
| Risk Manager | [01-risk-manager](./01-risk-manager/README.md) | `src/fdv_trader/domain/risk.py`、`src/fdv_trader/app/trading_service.py` |
| Order Executor | [02-order-executor](./02-order-executor/README.md) | `src/fdv_trader/infra/polymarket/order_executor.py` |
| FAK BUY 流程 | [03-fak-buy-flow](./03-fak-buy-flow/README.md) | `src/fdv_trader/app/trading_service.py`、`src/fdv_trader/domain/order.py` |
| GTC SELL 与 cancel + replace | [04-gtc-sell-cancel-replace](./04-gtc-sell-cancel-replace/README.md) | `src/fdv_trader/app/reconcile_service.py`、`order_executor.py` |
| 幂等、超时和执行器隔离 | [05-idempotency-timeouts](./05-idempotency-timeouts/README.md) | `src/fdv_trader/runtime`、`infra/polymarket` |

## 并行边界

- `Risk Manager` 只判断和返回结构化原因，不直接提交订单。
- `Order Executor` 只接收已通过风控的 intent，不重新拼接策略规则。
- FAK BUY 和 GTC SELL worker 可以并行，但必须共享 `OrderIntent`、`OrderResult`、`trace_id`、幂等键和审计事件名。
- 任何 P0 路径不得同步查询数据库、同步写日志落盘、无限等待锁或无超时调用外部 API。

