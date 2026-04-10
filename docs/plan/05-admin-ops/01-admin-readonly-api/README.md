# 01 Admin 只读查询 API 任务

## 覆盖范围

- 设计文档 `2.13 Admin API / CLI`
- 需求文档 `13. 管理功能`
- 设计文档 `1.7 高性能与交易优先级设计`

## Worker 任务

- 提供 target markets / eligible markets 查询。
- 提供每个 market 的 best bid/ask、spread、深度、资金分配、持仓、open orders 查询。
- 提供账户余额、USDC.e、allowance、positions、orders、fills 查询。
- 提供策略运行状态、WS 连接状态、最近 reconcile 时间查询。
- Admin API 查询只能读取快照或仓储层数据，禁止持有交易热状态写锁。
- 大查询必须分页和限流，不能与 Order Executor 共享线程池。
- API handler 只能调用应用服务，不能直接拼接 Polymarket payload，不能绕过 domain / app 边界。

## 交付物

- `/health`、`/ready` 以外的只读 Admin API 路由规划。
- `AdminService` 查询方法和响应 DTO。
- 分页、限流、快照读取和错误响应规范。

## 并行接口

- 上游：HTTP / CLI。
- 下游：AdminService、Market Registry 快照、Position 快照、repository。
- 与 `03-realtime-runtime/04-event-bus-priority-queues` 对齐快照读取策略。

## 注释要求

对禁止持有热状态写锁、分页限流、只读快照和不共享交易线程池写中文注释。开发阶段不运行测试。
