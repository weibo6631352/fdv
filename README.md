# Polymarket 单策略交易底座

这是一个 Polymarket 单策略后端运行时。
策略实现位于顶层 `src/strategies/`；执行、风控、恢复、审计和管理面由底座统一处理。

## 快速上手

先看这几个文件：

- 改 discovery 查询：[src/strategies/current/discovery.py](./src/strategies/current/discovery.py)
- 改市场筛选：[src/strategies/current/universe.py](./src/strategies/current/universe.py)
- 改策略配置：[src/strategies/current/config.py](./src/strategies/current/config.py)
- 改分配、入场、退出：[src/strategies/current/trading.py](./src/strategies/current/trading.py)
- 改恢复和保留跟踪：[src/strategies/current/recovery.py](./src/strategies/current/recovery.py) / [src/strategies/current/tracking.py](./src/strategies/current/tracking.py)
- 看策略装配入口：[src/strategies/current/strategy.py](./src/strategies/current/strategy.py)
- 看策略契约 SDK：[src/strategy_sdk](./src/strategy_sdk)

常用命令：

- 跑回归：`pytest -q`
- 跑静态检查：`ruff check .`
- 验证 PostgreSQL 链路：`pytest tests/infra/test_postgres_integration.py -q`
- 启动前端管理台：`npm --prefix frontend install && npm --prefix frontend run dev`
- 一键启动全部服务并打开前端：`./start_all.sh`
- 构建前端 dist：`./build_dist.sh`

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
| Frontend | [frontend](./frontend/README.md) | 管理台前端、通用 UI 与策略展示扩展槽 |
| Strategy SDK | [strategy_sdk](./src/strategy_sdk) | 策略契约、上下文对象、运行时 profile、配置加载 |
| Strategies | [strategies](./src/strategies) | 顶层策略实现包 |
| Workers | [workers](./src/polymarket_trader/workers/README.md) | 常驻后台任务 |
| Tests | [tests](./tests/README.md) | 单元、编排和基础设施测试 |

## 文档入口

- [当前策略需求文档](./docs/需求文档.md)：业务规则和风控边界。
- [当前策略设计文档](./docs/设计文档.md)：运行时装配和关键流程。
- [配置文档](./docs/config.md)：`.env`、策略模块加载和策略侧配置文件。
- [API 文档](./docs/api.md)：Admin API。
- [SDK 手续费说明](./docs/sdk-fees.md)：手续费公式、SDK 调用方式和 `fee_preview` 结构。
- [前端开发清单](./docs/frontend-开发清单.md)：前端边界、模块拆分和二次开发入口。
- [故障处理](./docs/runbook.md)：启动检查、异常排查顺序和人工恢复路径。

## 策略与测试入口

- 策略 manifest：[src/strategies/current/manifest.py](./src/strategies/current/manifest.py)
- 运行入口：[src/strategies/current/strategy.py](./src/strategies/current/strategy.py)
- 策略配置：[src/strategies/current/config.py](./src/strategies/current/config.py)
- discovery / universe：[src/strategies/current/discovery.py](./src/strategies/current/discovery.py) / [src/strategies/current/universe.py](./src/strategies/current/universe.py)
- 交易决策：[src/strategies/current/trading.py](./src/strategies/current/trading.py)
- 恢复 / 跟踪：[src/strategies/current/recovery.py](./src/strategies/current/recovery.py) / [src/strategies/current/tracking.py](./src/strategies/current/tracking.py)
- 契约 SDK：[src/strategy_sdk/interfaces.py](./src/strategy_sdk/interfaces.py) / [src/strategy_sdk/models.py](./src/strategy_sdk/models.py)

## 模块接口原则

- Domain 层只能使用系统内部 DTO，不依赖 FastAPI、SQLAlchemy、Polymarket SDK、WebSocket client 或环境变量。
- App 层负责编排用例，不直接拼接 Polymarket payload，不绕过 Domain 的规则对象。
- Infra 层负责外部协议适配，必须把 Polymarket / DB / WS 的响应转换为内部 DTO 后再向上返回。
- Order Executor 是唯一允许创建、签名、提交、取消和替换订单的模块。
- Risk Manager 是任何下单前的强制门禁。新增下单入口必须显式经过 Risk Manager。
- Admin API 只能调用应用服务，不能直接碰交易热状态写锁，不能绕过风控。
- Persistence Worker 和数据库写入只能异步承接 outbox 事件，不能反向阻塞交易主链路。
