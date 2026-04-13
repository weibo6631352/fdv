# Polymarket 单策略交易底座

这是一个 Polymarket 单策略后端运行时。
策略语义收口在 `src/polymarket_trader/strategies/current/`；执行、风控、恢复、审计和管理面由底座统一处理。

## 快速上手

先看这几个文件：

- 改市场筛选：[src/polymarket_trader/strategies/current/market_filter.py](./src/polymarket_trader/strategies/current/market_filter.py)
- 改交易阈值：[src/polymarket_trader/strategies/current/config.py](./src/polymarket_trader/strategies/current/config.py)
- 改分配、入场、退出、恢复：[src/polymarket_trader/strategies/current/trading_strategy.py](./src/polymarket_trader/strategies/current/trading_strategy.py)
- 改订阅保留与移除：[src/polymarket_trader/strategies/current/subscription.py](./src/polymarket_trader/strategies/current/subscription.py)
- 看运行入口：[src/polymarket_trader/strategies/current/strategy.py](./src/polymarket_trader/strategies/current/strategy.py)

常用命令：

- 跑回归：`pytest -q`
- 跑静态检查：`ruff check .`
- 验证 PostgreSQL 链路：`pytest tests/infra/test_postgres_integration.py -q`

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

- [当前策略需求文档](./docs/需求文档.md)：业务规则和风控边界。
- [当前策略设计文档](./docs/设计文档.md)：运行时装配和关键流程。
- [配置文档](./docs/config.md)：`.env` 和策略侧 Python 常量。
- [API 文档](./docs/api.md)：Admin API。
- [运行说明](./docs/operations.md)：启动、停止、人工操作。
- [故障处理](./docs/runbook.md)：异常排查顺序。

## 策略与测试入口

- 运行入口：[src/polymarket_trader/strategies/current/strategy.py](./src/polymarket_trader/strategies/current/strategy.py)
- 阈值常量：[src/polymarket_trader/strategies/current/config.py](./src/polymarket_trader/strategies/current/config.py)
- 市场筛选：[src/polymarket_trader/strategies/current/market_filter.py](./src/polymarket_trader/strategies/current/market_filter.py)
- 交易决策：[src/polymarket_trader/strategies/current/trading_strategy.py](./src/polymarket_trader/strategies/current/trading_strategy.py)
- 订阅规则：[src/polymarket_trader/strategies/current/subscription.py](./src/polymarket_trader/strategies/current/subscription.py)

## 模块接口原则

- Domain 层只能使用系统内部 DTO，不依赖 FastAPI、SQLAlchemy、Polymarket SDK、WebSocket client 或环境变量。
- App 层负责编排用例，不直接拼接 Polymarket payload，不绕过 Domain 的规则对象。
- Infra 层负责外部协议适配，必须把 Polymarket / DB / WS 的响应转换为内部 DTO 后再向上返回。
- Order Executor 是唯一允许创建、签名、提交、取消和替换订单的模块。
- Risk Manager 是任何下单前的强制门禁。新增下单入口必须显式经过 Risk Manager。
- Admin API 只能调用应用服务，不能直接碰交易热状态写锁，不能绕过风控。
- Persistence Worker 和数据库写入只能异步承接 outbox 事件，不能反向阻塞交易主链路。
