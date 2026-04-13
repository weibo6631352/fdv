# 配置说明

配置通过环境变量或等价的 typed settings 加载。配置项用于描述运行环境、策略风控、性能边界和外部依赖，不允许把密钥或运行时状态写死在源码中。

## 配置分组

| 分组 | 示例 | 说明 |
| --- | --- | --- |
| Polymarket 地址 | `POLYMARKET_CLOB_HOST`、`POLYMARKET_MARKET_WS` | 外部 API / WS 地址 |
| 组合预算 | `PORTFOLIO_BUDGET_USDC`、`MAX_ORDER_USDC`、`MAX_MARKET_USDC` | 控制总预算、单笔和单 market 上限 |
| 策略价格 | `ENTRY_NO_PRICE_MAX`、`EXIT_NO_PRICE` | 默认应保持 `0.60` 和 `0.70` |
| 风控阈值 | `MIN_LIQUIDITY_USDC`、`MAX_SPREAD`、`MAX_OPEN_ORDERS` | 下单前硬门禁 |
| 策略配置 | `STRATEGY_CONFIG_PATH` | 当前固定策略入口读取的 `.json` / `.toml` 配置文件路径 |
| 同步与重试 | `MARKET_SYNC_INTERVAL_SECONDS`、`ORDER_RETRY_LIMIT` | reconcile 与失败处理 |
| 性能隔离 | `TRADING_EVENT_QUEUE_MAX_SIZE`、`TRADING_WORKER_THREADS` | 交易主链路与后台维护 / 异步支撑队列及执行器隔离 |
| 超时告警 | `ORDER_SUBMIT_TIMEOUT_MS`、`CRITICAL_LOCK_TIMEOUT_MS` | 防止交易链路无限等待 |
| 数据库 | `DATABASE_URL`、`DATABASE_HOST` | PostgreSQL 连接地址；支持完整 URL 或拆分字段 |
| 密钥 | `POLYMARKET_API_KEY`、`WALLET_PRIVATE_KEY` | 只能通过安全环境注入 |

## 默认值原则

- 与策略语义强相关的值必须显式命名，例如 `ENTRY_NO_PRICE_MAX`。
- 会影响资金风险的配置应默认保守，不能默认放大仓位。
- 队列容量和线程池大小必须有上限，禁止无限队列。
- 超时配置必须有明确单位，变量名统一使用 `_MS` 或 `_SECONDS`。

数据库初始化约定：
- 开发环境先准备 PostgreSQL，再调用 `polymarket_trader.infra.db.initialize_database` 按当前 metadata 建表。
- 当前阶段不维护历史 schema 兼容层；模型调整后可以直接重建开发库再初始化。

数据库连接加载约定：
- `DATABASE_URL` 优先级最高；一旦填写，`DATABASE_DRIVER`、`DATABASE_HOST`、`DATABASE_PORT`、`DATABASE_NAME`、`DATABASE_USER`、`DATABASE_PASSWORD` 会被忽略。
- 当 `DATABASE_URL` 为空时，运行时会用上述拆分字段拼接 PostgreSQL 连接串。

策略配置约定：
- `STRATEGY_CONFIG_PATH` 指向当前策略入口读取的结构化配置文件，不指向 `strategy.py` 本身。
- 当前固定策略入口在 `src/polymarket_trader/strategies/current/strategy.py`。
- 当前内置加载器支持 `.json` 和 `.toml`。
- 远端发现查询参数不放环境变量里堆砌；这类官方 Gamma 查询参数由策略代码里的 `build_discovery_queries()` 直接声明并透传。

## 密钥规则

不得提交到仓库：
- Polymarket API key / secret / passphrase。
- wallet private key 或 signer 配置。
- builder attribution credentials。
- 数据库密码和生产连接串。

日志和审计事件中不得输出：
- 完整签名 payload。
- 私钥、API secret、passphrase。
- 未脱敏 raw response 中的敏感账户字段。

## 新增配置交接清单

新增配置项时，需要说明：
- 属于交易主链路、关键修复链路、后台维护链路还是异步支撑链路。
- 默认值是什么，默认值是否安全。
- 单位是什么，取值范围是什么。
- 是否可以运行时热更新。
- 是否需要写入 [`.env.example`](../.env.example)。
- 是否会改变资金暴露、订单行为或 reconcile 行为。
