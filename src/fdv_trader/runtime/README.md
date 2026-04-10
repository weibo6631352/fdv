# runtime 目录说明

该目录存放进程运行时组件，包括事件队列、状态注册表、调度和 supervisor。Runtime 的核心任务是保护 P0 交易链路的优先级和状态一致性。

## 文件职责

- `event_bus.py`：事件总线和优先级队列。
- `registry.py`：market / token 索引和本地状态注册表。
- `status.py`：runtime phase、readiness、scheduler snapshot 和 worker health 契约。
- `scheduler.py`：任务创建与调度。
- `supervisor.py`：worker 生命周期、降级、暂停和恢复。

## 优先级定义

- P0：Orderbook Watcher、Strategy Worker、Risk Manager、Order Executor、User WS 中的订单 / 成交状态更新。
- P1：关键修复动作，例如取消异常 open BUY、补挂缺失 SELL。
- P2：Market Discovery、周期 reconcile、余额和 allowance 周期检查。
- P3：Persistence Worker、指标聚合、Admin 普通查询、报表。

## 允许依赖

- `fdv_trader.domain` 的状态模型和事件。
- `fdv_trader.config` 的队列容量和超时配置。
- `fdv_trader.observability` 的指标和 trace。

## 禁止行为

- 不在 runtime 中实现 Polymarket API 适配。
- 不在 registry 中做慢数据库查询。
- 不使用全局大锁保护所有 market / position / orderbook 状态。
- 不让 P2 / P3 任务持有会阻塞 P0 写入的锁。

## 状态访问规则

- 按 `condition_id` 或 `token_id` 分片。
- Admin 和 Persistence 读取快照，不直接持有热状态写锁。
- P0 写入只做短临界区更新。
- 非关键锁等待超时后跳过并告警，不能无限等待。

## 交接清单

新增队列、锁或调度任务时，必须说明：
- 所属优先级。
- 最大容量。
- 最大等待时间。
- 超时后的降级策略。
- 是否影响 P0 交易路径。
