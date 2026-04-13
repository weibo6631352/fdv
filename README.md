# Polymarket 单策略交易底座

本仓库提供一个面向 Polymarket 的单策略后端运行时。底座负责交易链路优先级、风控编排、恢复、审计、管理面和外部适配；具体 universe 选择、入场和退出语义收口在当前策略实现中。

框架约束以通用分层和运行时边界为准；当前策略约束以 [当前策略需求文档](./docs/需求文档.md) 和 [当前策略设计文档](./docs/设计文档.md) 为准。

## 核心规则

- 单个 runtime 只装配一个当前策略实现。
- 交易标的、入场规则、退出规则和 universe 选择由当前策略定义。
- 买入侧不得保留长期 resting BUY order；一旦发现 open BUY 异常，必须立即进入 cancel / reconcile 修复流程。
- 资金分配、订单执行、恢复、审计和管理面必须经过统一服务编排。
- 数据库用于审计、复盘、调试和恢复参考，不作为交易状态唯一真相来源。
- 交易主链路优先级最高，不得被 Admin 查询、数据库写入、日志落盘、全量 market 扫描、报表或低优先级 reconcile 阻塞。

## 架构分层

代码采用 `src` layout，主包是 [src/polymarket_trader](./src/polymarket_trader/README.md)。

| 层级 | 目录 | 主要职责 |
| --- | --- | --- |
| Interfaces | [api](./src/polymarket_trader/api/README.md) | Admin API、健康检查 |
| Application | [app](./src/polymarket_trader/app/README.md) | 用例编排，组合 domain 与 infra |
| Domain | [domain](./src/polymarket_trader/domain/README.md) | 分类、分配、风控、策略、订单和持仓规则 |
| Infrastructure | [infra](./src/polymarket_trader/infra/README.md) | Polymarket、数据库、outbox 和外部 I/O 适配 |
| Observability | [observability](./src/polymarket_trader/observability/README.md) | 审计、trace、指标 |
| Runtime | [runtime](./src/polymarket_trader/runtime/README.md) | 事件总线、状态注册表、调度、supervisor |
| Workers | [workers](./src/polymarket_trader/workers/README.md) | 常驻后台任务 |
| Tests | [tests](./tests/README.md) | 单元、编排和基础设施测试 |

## 文档入口

- [当前策略需求文档](./docs/需求文档.md)：当前内置策略的业务规则、风控边界和策略约束。
- [当前策略设计文档](./docs/设计文档.md)：当前内置策略及运行时装配设计。
- [API 文档](./docs/api.md)：对外 HTTP 接口、请求参数和响应结构。
- [配置文档](./docs/config.md)：环境变量和配置项说明。
- [运行说明](./docs/operations.md)：启动方式、运行状态和常用运维查看项。
- [故障处理](./docs/runbook.md)：异常定位和处理步骤。

## 策略与测试入口

- 当前运行策略固定在 [src/polymarket_trader/strategies/current/strategy.py](./src/polymarket_trader/strategies/current/strategy.py)。
- 策略业务参数定义位于 [src/polymarket_trader/strategies/current/config.py](./src/polymarket_trader/strategies/current/config.py)，不再通过 `.env` 注入。
- 市场筛选位于 [src/polymarket_trader/strategies/current/market_filter.py](./src/polymarket_trader/strategies/current/market_filter.py)。
- 交易决策位于 [src/polymarket_trader/strategies/current/trading_strategy.py](./src/polymarket_trader/strategies/current/trading_strategy.py)。
- 订阅保留与移除规则位于 [src/polymarket_trader/strategies/current/subscription.py](./src/polymarket_trader/strategies/current/subscription.py)。
- 远端市场发现由 `build_discovery_queries()` 提供官方 Gamma 查询参数，框架只透传查询；最终是否纳入 universe，仍由 `select_market()` 决定。
- 日常本地回归直接运行 `pytest`。
- PostgreSQL 集成测试默认允许跳过；需要验证真实建表和持久化链路时，先设置 `TRADER_TEST_POSTGRES_DSN` 再运行 `pytest tests/infra/test_postgres_integration.py -q`。

## 模块接口原则

- Domain 层只能使用系统内部 DTO，不依赖 FastAPI、SQLAlchemy、Polymarket SDK、WebSocket client 或环境变量。
- App 层负责编排用例，不直接拼接 Polymarket payload，不绕过 Domain 的规则对象。
- Infra 层负责外部协议适配，必须把 Polymarket / DB / WS 的响应转换为内部 DTO 后再向上返回。
- Order Executor 是唯一允许创建、签名、提交、取消和替换订单的模块。
- Risk Manager 是任何下单前的强制门禁。新增下单入口必须显式经过 Risk Manager。
- Admin API 只能调用应用服务，不能直接碰交易热状态写锁，不能绕过风控。
- Persistence Worker 和数据库写入只能异步承接 outbox 事件，不能反向阻塞交易主链路。
