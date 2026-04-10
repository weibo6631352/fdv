# workers 目录说明

该目录存放常驻后台任务。Worker 负责从队列、WebSocket、定时器或外部事件中取数据，然后调用 App 层服务完成编排。

## 文件职责

- `market_discovery_worker.py`：P2，发现 active events / markets，触发分类。
- `market_ws_worker.py`：P0，接收 target market orderbook 和 best bid / ask 更新。
- `user_ws_worker.py`：P0，接收订单、成交、持仓生命周期事件。
- `strategy_worker.py`：P0，消费交易事件并生成订单意图。
- `reconcile_worker.py`：P2，周期校准权威状态，必要修复动作升级到 P1 / P0。
- `persistence_worker.py`：P3，消费 outbox 异步落库。

## 允许依赖

- `fdv_trader.app` 应用服务。
- `fdv_trader.runtime` 队列和调度。
- `fdv_trader.observability` 指标和 trace。

## 禁止行为

- Worker 不直接实现业务规则。
- Worker 不直接调用 Polymarket SDK；需要通过 app / infra 边界。
- P0 worker 不等待 P2 / P3 worker 释放资源。
- Persistence Worker 不反向调用 Strategy 或 Order Executor。
- Reconciler 不在批量扫描任务中长时间持有交易状态写锁。

## 交接清单

新增 worker 时，需要说明：
- 优先级 P0 / P1 / P2 / P3。
- 输入事件来源。
- 输出事件或调用的 app service。
- 队列容量和背压策略。
- 失败重试与审计事件。
- 是否需要独立线程池或进程池。

