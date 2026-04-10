# 05 配置与密钥任务

## 覆盖范围

- 设计文档 `4.3 配置设计`
- 设计文档 `5.1 编码与文件格式`
- 需求文档 `9. 风控`

## Worker 任务

- 提供 typed settings，配置来源为环境变量和 `.env.example` 示例。
- 覆盖 Polymarket 端点：`POLYMARKET_CLOB_HOST`、`POLYMARKET_GAMMA_HOST`、`POLYMARKET_DATA_HOST`、`POLYMARKET_MARKET_WS`、`POLYMARKET_USER_WS`。
- 覆盖策略与风控：`PORTFOLIO_BUDGET_USDC`、`MAX_ORDER_USDC`、`MAX_MARKET_USDC`、`MAX_TOTAL_USDC`、`ENTRY_NO_PRICE_MAX=0.60`、`EXIT_NO_PRICE=0.70`、`MIN_LIQUIDITY_USDC`、`MAX_SPREAD`、`MARKET_SYNC_INTERVAL_SECONDS`、`ORDER_RETRY_LIMIT`、`MAX_OPEN_ORDERS`。
- 覆盖性能与优先级：`ENABLE_UVLOOP`、队列容量、线程池/进程池大小、订单签名/提交超时、关键锁超时、队列深度告警、`ENTRY_SIGNAL_TO_SUBMIT_WARN_MS`。
- 覆盖数据库：`DATABASE_URL`。
- 明确密钥类配置不得进入仓库：Polymarket API key / secret / passphrase、wallet private key 或 signer 配置、builder attribution credentials、数据库密码。
- 配置加载失败时输出结构化原因，启动阶段禁止进入自动下单。

## 交付物

- 配置对象、默认值策略和必填项校验。
- `.env.example` 字段说明。
- 敏感字段红action / 脱敏显示策略。

## 并行接口

- 上游：所有 worker 读取配置对象。
- 下游：外部 clients、Risk Manager、Scheduler、Event Bus、Persistence Worker。
- 与 `06-observability-docs/03-logging-redaction` 对齐敏感字段脱敏规则。

## 注释要求

对配置分组、默认值风险、密钥禁止入库和启动失败时禁止自动下单写中文注释。开发阶段不运行测试。

