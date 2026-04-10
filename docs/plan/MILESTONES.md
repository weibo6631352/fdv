# 开发里程碑与状态表

本文件用于在自动开发过程中记录里程碑、任务状态、worker 分配和集成备注。开发过程中不要求补充或运行验证测试；验证测试统一进入 M5 专项验收阶段。

## 状态约定

| 状态 | 含义 |
| --- | --- |
| `pending` | 尚未开始 |
| `in_progress` | 正在开发 |
| `blocked` | 被接口、依赖或上下文阻塞 |
| `integrating` | 子任务完成，正在主线集成 |
| `done` | 开发交付完成，未运行验证测试 |
| `deferred` | 暂缓，不影响当前里程碑 |

## 里程碑

| 里程碑 | 目标 | 完成标准 |
| --- | --- | --- |
| M0 契约优先 | 统一 DTO、事件、配置、审计字段和 worker 边界 | 领域 DTO、配置对象、审计事件名、outbox 幂等键的字段名可被各组引用 |
| M1 核心规则 | 完成分类、registry、allocation、risk、orderbook 和 event bus 基础能力 | 可从 market 发现走到 `EntryPriceTouched`、allocation 和 risk result |
| M2 交易流程 | 完成 FAK BUY、GTC SELL、cancel + replace、Position Manager 和 reconcile 修复 | 买入、成交处理、卖单补挂、异常 open BUY cancel 的代码路径可串联 |
| M3 基础设施 | 完成 Polymarket clients、DB repository、outbox、Persistence Worker 和配置密钥 | 外部协议适配与异步持久化链路可供应用层调用 |
| M4 运维与降级 | 完成 Admin API / CLI、startup bootstrap、scheduler、supervisor、metrics、logging 和 runbook | 启动恢复、健康检查、人工 SELL 操作、P2 / P3 降级和告警路径明确 |
| M5 专项验收 | 按验收测试计划补齐并运行测试 | 验收阶段执行，不属于当前开发阶段默认动作 |

## 任务状态

| 任务 | 里程碑 | 建议 worker | 状态 | 依赖 | 集成备注 |
| --- | --- | --- | --- | --- | --- |
| [领域 DTO 与事件契约](./01-strategy-domain/05-domain-dto-events/README.md) | M0 | W01 | done | 无 | 统一 DTO、领域事件名、订单/成交/持仓/分配字段契约，未运行验证测试 |
| [配置与密钥](./04-infra-persistence/05-config-secrets/README.md) | M0 | W02 | done | 无 | 配置对象、`.env.example`、启动 readiness 和脱敏输出，未运行验证测试 |
| [Audit / Trace](./06-observability-docs/01-audit-trace/README.md) | M0 | W03 | done | 领域事件契约 | 审计事件 schema、事件名、trace 传播和 raw response 脱敏，未运行验证测试 |
| [Outbox / Local Queue](./04-infra-persistence/03-outbox-local-queue/README.md) | M0 | W04 | done | 领域事件契约、审计字段 | 本地 outbox 契约、短超时 enqueue、retry/dead-letter 和幂等键，未运行验证测试 |
| [Market 分类](./01-strategy-domain/01-market-classifier/README.md) | M1 | W05 | pending | 领域 DTO | 纯 domain 实现 |
| [Market Registry 与模型](./01-strategy-domain/02-market-registry-models/README.md) | M1 | W06 | pending | 领域 DTO | 需支持快照读取 |
| [组合资金分配](./01-strategy-domain/03-portfolio-allocation/README.md) | M1 | W07 | pending | Registry、配置 | 输出 AllocationPlan |
| [Risk Manager](./02-trading-execution-risk/01-risk-manager/README.md) | M1 | W08 | pending | AllocationPlan、配置 | 只做门禁，不下单 |
| [Market Discovery / Streamer](./03-realtime-runtime/01-market-discovery-streamer/README.md) | M1 | W09 | pending | Polymarket client DTO | 输出 RawMarketEvent |
| [Market WS / Orderbook](./03-realtime-runtime/02-market-ws-orderbook/README.md) | M1 | W10 | pending | Registry、Event Bus | 输出 EntryPriceTouched |
| [Event Bus / Priority Queues](./03-realtime-runtime/04-event-bus-priority-queues/README.md) | M1 | W11 | pending | 配置 | P0 / P2 / P3 隔离 |
| [策略引擎与状态机](./01-strategy-domain/04-strategy-engine-state-machine/README.md) | M2 | W12 | pending | Allocation、Risk、Event Bus | 生成订单 intent |
| [Order Executor](./02-trading-execution-risk/02-order-executor/README.md) | M2 | W13 | pending | Outbox、Polymarket client | 唯一下单入口 |
| [FAK BUY 流程](./02-trading-execution-risk/03-fak-buy-flow/README.md) | M2 | W14 | pending | Strategy、Risk、Order Executor | P0 热路径 |
| [GTC SELL 与 cancel + replace](./02-trading-execution-risk/04-gtc-sell-cancel-replace/README.md) | M2 | W15 | pending | Order Executor、Position | 只对成交 shares 挂 SELL |
| [幂等、超时和执行器隔离](./02-trading-execution-risk/05-idempotency-timeouts/README.md) | M2 | W16 | pending | Event Bus、配置 | P0 不做慢 DB 查询 |
| [User WS / Position Manager](./03-realtime-runtime/03-user-ws-position-manager/README.md) | M2 | W17 | pending | Polymarket client、Registry | 按 condition id 订阅 |
| [Reconcile Worker](./03-realtime-runtime/05-reconcile-worker/README.md) | M2 | W18 | pending | Polymarket clients、Position、Order Executor | P2 扫描，P1/P0 修复 |
| [Polymarket Clients 与 Schemas](./04-infra-persistence/01-polymarket-clients-schemas/README.md) | M3 | W19 | pending | 配置 | raw payload 转内部 DTO |
| [DB 模型与 Repository](./04-infra-persistence/02-db-models-repositories/README.md) | M3 | W20 | pending | 领域 DTO、审计字段 | DB 不是交易状态唯一真相 |
| [Persistence Worker](./04-infra-persistence/04-persistence-worker/README.md) | M3 | W21 | pending | Outbox、Repository | P3 异步落库 |
| [Scheduler / Supervisor / Recovery](./03-realtime-runtime/06-scheduler-supervisor-recovery/README.md) | M4 | W22 | pending | Event Bus、metrics、配置 | 低优先级限速和恢复状态机 |
| [Admin 只读查询 API](./05-admin-ops/01-admin-readonly-api/README.md) | M4 | W23 | pending | Registry 快照、Repository | 分页限流，只读快照 |
| [Admin cancel + replace](./05-admin-ops/02-admin-cancel-replace/README.md) | M4 | W24 | pending | SELL 流程、Order Executor | 不提供 BUY 绕过路径 |
| [CLI / Health / Operations](./05-admin-ops/03-cli-health-operations/README.md) | M4 | W25 | pending | Startup、Supervisor | health 不触发慢查询 |
| [启动恢复](./05-admin-ops/04-startup-bootstrap/README.md) | M4 | W26 | pending | Config、clients、workers | 首次 reconcile 前禁自动下单 |
| [故障处置 Runbook](./05-admin-ops/05-runbook-failure-ops/README.md) | M4 | W27 | pending | Supervisor、metrics | 故障矩阵与人工动作 |
| [Metrics / Alerts](./06-observability-docs/02-metrics-alerts/README.md) | M4 | W28 | pending | Event Bus、Order Executor | 延迟与队列深度指标 |
| [Logging / Redaction](./06-observability-docs/03-logging-redaction/README.md) | M4 | W29 | pending | 配置、审计字段 | P0 不同步落盘 |
| [文档与注释规范](./06-observability-docs/04-docs-comments/README.md) | M4 | W30 | pending | 所有任务 | 审查注释和文档同步 |
| [验收测试计划](./06-observability-docs/05-acceptance-test-plan/README.md) | M5 | W31 | pending | M0-M4 | 验收阶段执行 |

## 记录规则

- 开始某个任务时，把状态改为 `in_progress`，并在集成备注写明 worker 负责的主要文件。
- 子任务完成但尚未主线串联时，把状态改为 `integrating`。
- 开发交付完成后，把状态改为 `done`，备注“未运行验证测试”。
- 遇到跨组字段不一致时，把相关任务标为 `blocked`，在备注中写明需要对齐的 DTO、事件或配置名。
- 不回滚其他 worker 或用户已经修改的文件；发现冲突时先记录在备注，再做最小范围协调。
- 不为通过测试或迁就临时调用方随意增加兼容层、旧字段别名、包装函数、重复枚举或同义常量；应优先修正调用方并统一到当前里程碑契约。确需兼容外部协议时，在对应任务 README 写明原因、边界和移除条件。
