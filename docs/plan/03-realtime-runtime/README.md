# 实时数据与运行时组

## 目标

负责实时 market 发现、WebSocket 订阅、状态热缓存、事件总线、优先级队列、reconcile、scheduler 和 supervisor。该组保护 P0 交易链路不被 P2 / P3 任务拖慢。

## 可并行任务

| 任务 | Worker 入口 | 主要模块 |
| --- | --- | --- |
| Market Discovery / Streamer | [01-market-discovery-streamer](./01-market-discovery-streamer/README.md) | `src/fdv_trader/workers/market_discovery_worker.py` |
| Market WS / Orderbook | [02-market-ws-orderbook](./02-market-ws-orderbook/README.md) | `src/fdv_trader/workers/market_ws_worker.py`、`domain/orderbook.py` |
| User WS / Position Manager | [03-user-ws-position-manager](./03-user-ws-position-manager/README.md) | `src/fdv_trader/workers/user_ws_worker.py`、`domain/position.py` |
| Event Bus / Priority Queues | [04-event-bus-priority-queues](./04-event-bus-priority-queues/README.md) | `src/fdv_trader/runtime/event_bus.py` |
| Reconcile Worker | [05-reconcile-worker](./05-reconcile-worker/README.md) | `src/fdv_trader/workers/reconcile_worker.py`、`app/reconcile_service.py` |
| Scheduler / Supervisor / Recovery | [06-scheduler-supervisor-recovery](./06-scheduler-supervisor-recovery/README.md) | `src/fdv_trader/runtime/scheduler.py`、`supervisor.py` |

## 并行边界

- Market WS、User WS 和 Reconcile 可以并行开发，但状态写入必须通过 registry /事件总线约定，不能各自持有全局大锁。
- P0 事件包括首次入场信号、订单状态、成交状态、异常 open BUY、cancel 修复和 SELL 补挂。
- P2 / P3 事件可以合并、降采样或延迟，不能反向阻塞 P0。
- 注释必须写清重连、快照覆盖、状态优先级、背压和锁超时策略。

