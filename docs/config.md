# 配置说明

先分清两类配置：

- 框架配置：写 `.env`
- 策略规则：写 `src/polymarket_trader/strategies/current/`

## 先看哪里

| 分组 | 示例 | 说明 |
| --- | --- | --- |
| Polymarket 地址 | `POLYMARKET_CLOB_HOST`、`POLYMARKET_MARKET_WS` | 外部 API / WS 地址 |
| 组合预算 | `PORTFOLIO_BUDGET_USDC`、`MAX_ORDER_USDC`、`MAX_MARKET_USDC` | 控制总预算、单笔和单 market 上限 |
| 框架风控阈值 | `MAX_OPEN_ORDERS` | 运行时公共风控门禁 |
| 同步与重试 | `MARKET_SYNC_INTERVAL_SECONDS`、`ORDER_RETRY_LIMIT` | reconcile 与失败处理 |
| 性能隔离 | `TRADING_EVENT_QUEUE_MAX_SIZE`、`TRADING_WORKER_THREADS` | 交易主链路与后台维护 / 异步支撑队列及执行器隔离 |
| 超时告警 | `ORDER_SUBMIT_TIMEOUT_MS`、`CRITICAL_LOCK_TIMEOUT_MS` | 防止交易链路无限等待 |
| 数据库 | `DATABASE_URL`、`DATABASE_HOST` | PostgreSQL 连接地址；支持完整 URL 或拆分字段 |
| 密钥 | `POLYMARKET_API_KEY`、`WALLET_PRIVATE_KEY` | 只能通过安全环境注入 |
| 策略规则 | `strategies/current/` | 交易阈值、筛选语义、订阅规则 |

## 规则

- 单一策略语义，不新增环境变量，直接写 `strategies/current/`。
- 会影响资金风险的配置应默认保守，不能默认放大仓位。
- 队列和线程池必须有上限。
- 超时字段统一用 `_MS` 或 `_SECONDS`。

## 数据库

- 开发环境先准备 PostgreSQL，再调用 `polymarket_trader.infra.db.initialize_database` 按当前 metadata 建表。
- schema 改动不兼容时，直接重建开发库再初始化。

连接顺序：
- `DATABASE_URL` 优先级最高；一旦填写，`DATABASE_DRIVER`、`DATABASE_HOST`、`DATABASE_PORT`、`DATABASE_NAME`、`DATABASE_USER`、`DATABASE_PASSWORD` 会被忽略。
- 当 `DATABASE_URL` 为空时，运行时会用上述拆分字段拼接 PostgreSQL 连接串。

## 策略文件

- 入口：`src/polymarket_trader/strategies/current/strategy.py`
- 阈值常量：`src/polymarket_trader/strategies/current/config.py`
- 市场筛选：`market_filter.py`
- 交易决策：`trading_strategy.py`
- 订阅规则：`subscription.py`

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

## 新增配置时确认

- 属于交易主链路、关键修复链路、后台维护链路还是异步支撑链路。
- 默认值是什么，默认值是否安全。
- 单位是什么，取值范围是什么。
- 是否可以运行时热更新。
- 是否需要写入 [`.env.example`](../.env.example)。
- 如果只是策略规则，直接写 `strategies/current/`，不要新增环境变量。
- 是否会改变资金暴露、订单行为或 reconcile 行为。
