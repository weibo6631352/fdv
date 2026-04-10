# 开发规划总览

本目录用于把 [设计文档](../设计文档.md) 的技术要点拆成可并行交付的 worker 任务。目录结构约定：

```text
docs/plan/
├── 01-strategy-domain/          # 策略与领域模型组
├── 02-trading-execution-risk/   # 交易执行与风控组
├── 03-realtime-runtime/         # 实时数据与运行时组
├── 04-infra-persistence/        # 基础设施与持久化组
├── 05-admin-ops/                # Admin API 与运维组
└── 06-observability-docs/       # 可观测与文档规范组
```

## 阶段规则

- 开发过程中不运行测试；验证测试由 `06-observability-docs/05-acceptance-test-plan` 在专项验收阶段统一安排。
- 每个 worker 只改自己任务文档声明的主要模块，跨组接口先对齐 DTO、事件、配置名和审计字段，再并行实现。
- 涉及交易热路径的任务必须标注 P0 / P1 / P2 / P3 优先级，说明锁、队列、线程池、超时和降级策略。
- 注释必须解释关键业务规则、状态不变量、外部 API 字段差异、异常降级原因和违反约束的后果，避免复述代码语法。

自动开发时按 [MILESTONES.md](./MILESTONES.md) 记录任务状态、worker 分配、依赖和集成备注。

## 项目组入口

| 项目组 | 入口 | 主要覆盖范围 |
| --- | --- | --- |
| 策略与领域模型组 | [01-strategy-domain](./01-strategy-domain/README.md) | Market Classifier、Market Registry、Portfolio Allocator、Strategy Engine、领域 DTO / 事件 |
| 交易执行与风控组 | [02-trading-execution-risk](./02-trading-execution-risk/README.md) | Risk Manager、Order Executor、FAK BUY、GTC SELL、cancel + replace、幂等与超时 |
| 实时数据与运行时组 | [03-realtime-runtime](./03-realtime-runtime/README.md) | Market Streamer、Orderbook Watcher、User WS、Position Manager、Reconciler、事件总线、supervisor |
| 基础设施与持久化组 | [04-infra-persistence](./04-infra-persistence/README.md) | Polymarket API / WS 适配、数据库模型、repository、outbox、Persistence Worker、配置与密钥 |
| Admin API 与运维组 | [05-admin-ops](./05-admin-ops/README.md) | Admin API / CLI、启动恢复、人工操作、健康检查、运维 runbook |
| 可观测与文档规范组 | [06-observability-docs](./06-observability-docs/README.md) | Audit Logger、trace、metrics、日志脱敏、文档规范、验收测试计划 |

## 覆盖矩阵

| 设计文档章节 | 负责计划 |
| --- | --- |
| 1.1 设计目标 | 全组共同遵守，P0 交易优先级由 [03-realtime-runtime/04-event-bus-priority-queues](./03-realtime-runtime/04-event-bus-priority-queues/README.md) 牵头 |
| 1.2 推荐技术栈 | [04-infra-persistence/05-config-secrets](./04-infra-persistence/05-config-secrets/README.md)、[03-realtime-runtime/06-scheduler-supervisor-recovery](./03-realtime-runtime/06-scheduler-supervisor-recovery/README.md) |
| 1.3-1.5 总体架构、分层、运行时组件 | 6 个项目组 README 与各任务目录共同覆盖 |
| 1.6 状态真相来源 | [03-realtime-runtime/05-reconcile-worker](./03-realtime-runtime/05-reconcile-worker/README.md)、[05-admin-ops/04-startup-bootstrap](./05-admin-ops/04-startup-bootstrap/README.md) |
| 1.7 高性能与交易优先级 | [03-realtime-runtime/04-event-bus-priority-queues](./03-realtime-runtime/04-event-bus-priority-queues/README.md)、[02-trading-execution-risk/05-idempotency-timeouts](./02-trading-execution-risk/05-idempotency-timeouts/README.md)、[06-observability-docs/02-metrics-alerts](./06-observability-docs/02-metrics-alerts/README.md) |
| 2.1 Market Streamer | [03-realtime-runtime/01-market-discovery-streamer](./03-realtime-runtime/01-market-discovery-streamer/README.md) |
| 2.2 Market Classifier | [01-strategy-domain/01-market-classifier](./01-strategy-domain/01-market-classifier/README.md) |
| 2.3 Market Registry | [01-strategy-domain/02-market-registry-models](./01-strategy-domain/02-market-registry-models/README.md) |
| 2.4 Orderbook Watcher | [03-realtime-runtime/02-market-ws-orderbook](./03-realtime-runtime/02-market-ws-orderbook/README.md) |
| 2.5 Portfolio Allocator | [01-strategy-domain/03-portfolio-allocation](./01-strategy-domain/03-portfolio-allocation/README.md) |
| 2.6 Risk Manager | [02-trading-execution-risk/01-risk-manager](./02-trading-execution-risk/01-risk-manager/README.md) |
| 2.7 Strategy Engine | [01-strategy-domain/04-strategy-engine-state-machine](./01-strategy-domain/04-strategy-engine-state-machine/README.md) |
| 2.8 Order Executor | [02-trading-execution-risk/02-order-executor](./02-trading-execution-risk/02-order-executor/README.md) |
| 2.9 Position Manager | [03-realtime-runtime/03-user-ws-position-manager](./03-realtime-runtime/03-user-ws-position-manager/README.md) |
| 2.10 Reconciler | [03-realtime-runtime/05-reconcile-worker](./03-realtime-runtime/05-reconcile-worker/README.md) |
| 2.11 Audit Logger | [06-observability-docs/01-audit-trace](./06-observability-docs/01-audit-trace/README.md) |
| 2.12 Persistence Worker | [04-infra-persistence/04-persistence-worker](./04-infra-persistence/04-persistence-worker/README.md) |
| 2.13 Admin API / CLI | [05-admin-ops/01-admin-readonly-api](./05-admin-ops/01-admin-readonly-api/README.md)、[05-admin-ops/02-admin-cancel-replace](./05-admin-ops/02-admin-cancel-replace/README.md)、[05-admin-ops/03-cli-health-operations](./05-admin-ops/03-cli-health-operations/README.md) |
| 3.1 系统启动流程 | [05-admin-ops/04-startup-bootstrap](./05-admin-ops/04-startup-bootstrap/README.md) |
| 3.2 Market 发现与筛选流程 | [03-realtime-runtime/01-market-discovery-streamer](./03-realtime-runtime/01-market-discovery-streamer/README.md)、[01-strategy-domain/01-market-classifier](./01-strategy-domain/01-market-classifier/README.md) |
| 3.3 Orderbook 监听与入场信号流程 | [03-realtime-runtime/02-market-ws-orderbook](./03-realtime-runtime/02-market-ws-orderbook/README.md)、[01-strategy-domain/04-strategy-engine-state-machine](./01-strategy-domain/04-strategy-engine-state-machine/README.md) |
| 3.4 FAK 买入流程 | [02-trading-execution-risk/03-fak-buy-flow](./02-trading-execution-risk/03-fak-buy-flow/README.md) |
| 3.5 GTC 卖出流程 | [02-trading-execution-risk/04-gtc-sell-cancel-replace](./02-trading-execution-risk/04-gtc-sell-cancel-replace/README.md) |
| 3.6 资金再分配流程 | [01-strategy-domain/03-portfolio-allocation](./01-strategy-domain/03-portfolio-allocation/README.md) |
| 3.7 Reconcile 流程 | [03-realtime-runtime/05-reconcile-worker](./03-realtime-runtime/05-reconcile-worker/README.md) |
| 3.8 Admin cancel + replace 流程 | [05-admin-ops/02-admin-cancel-replace](./05-admin-ops/02-admin-cancel-replace/README.md) |
| 3.9 异常处理流程 | [05-admin-ops/05-runbook-failure-ops](./05-admin-ops/05-runbook-failure-ops/README.md)、[03-realtime-runtime/06-scheduler-supervisor-recovery](./03-realtime-runtime/06-scheduler-supervisor-recovery/README.md) |
| 3.10 高优先级交易事件处理流程 | [03-realtime-runtime/04-event-bus-priority-queues](./03-realtime-runtime/04-event-bus-priority-queues/README.md)、[02-trading-execution-risk/05-idempotency-timeouts](./02-trading-execution-risk/05-idempotency-timeouts/README.md) |
| 4.1-4.3 目录、数据模型、配置 | [01-strategy-domain/05-domain-dto-events](./01-strategy-domain/05-domain-dto-events/README.md)、[04-infra-persistence/02-db-models-repositories](./04-infra-persistence/02-db-models-repositories/README.md)、[04-infra-persistence/05-config-secrets](./04-infra-persistence/05-config-secrets/README.md) |
| 4.4 测试重点 | [06-observability-docs/05-acceptance-test-plan](./06-observability-docs/05-acceptance-test-plan/README.md) |
| 5.1-5.4 开发规范 | [06-observability-docs/04-docs-comments](./06-observability-docs/04-docs-comments/README.md)、各任务 README 的并发与注释约束 |
