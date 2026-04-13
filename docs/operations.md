# 运维说明

该文档用于记录部署、启动、停止、升级和人工操作约定。运维动作的首要目标是保持交易状态可确认、可恢复，而不是强行让服务继续下单。

## 管理面边界

- 当前 Admin API 默认只允许在本机或受控内网暴露，不提供应用层鉴权。
- 对外 HTTP 接口清单、请求参数和返回结构以 [api.md](./api.md) 为准。
- 当前受控写接口只有 `POST /operations/reconcile` 和 `POST /orders/cancel-replace-sell`。
- 后端进程直接通过 ASGI 启动，不再维护单独 CLI 壳子。

## 初始启动顺序

1. 准备环境变量，确认密钥不在仓库内。
2. 准备 PostgreSQL。开发机可以直接使用系统服务：
   `sudo apt-get update && sudo apt-get install -y postgresql postgresql-client`
3. 创建开发库和账户：
   `sudo -u postgres psql -c "CREATE USER trader WITH PASSWORD 'trader';"`
   `sudo -u postgres psql -c "CREATE DATABASE trader OWNER trader;"`
   已存在时改为执行 `ALTER USER` / `ALTER DATABASE OWNER`。
4. 参考 [`.env.example`](../.env.example) 填写 `.env` 中的数据库字段或 `DATABASE_URL`。
5. 调用 `polymarket_trader.infra.db.initialize_database`，按当前 SQLAlchemy metadata 创建开发库表结构。
6. 启动服务：`uvicorn polymarket_trader.api.app:create_app --factory --host 127.0.0.1 --port 8000`。
7. 服务启动时会依次完成配置校验、日志初始化、线程池/进程池创建、数据库连通性检查、参考快照加载和首次 reconcile。
8. 先检查 `/health`，确认进程存活；再检查 `/ready`，确认 DB、交易客户端、WS 状态、outbox 和自动下单闸门。
9. 用 `/runtime` 查看 phase、队列深度、最近 reconcile、Persistence backlog 和降级状态。
10. 当 `/ready` 的 `ready_to_trade` 为 `true` 且 runtime phase 为 `trading_enabled` 时，才允许自动下单。

## 常用命令

- 启动服务：`uvicorn polymarket_trader.api.app:create_app --factory --host 127.0.0.1 --port 8000`
- 初始化数据库：调用 `polymarket_trader.infra.db.initialize_database`
- 查看运行状态：`GET /runtime`
- 触发受控 reconcile：`POST /operations/reconcile`
- 本地策略回放：调用 `polymarket_trader.strategy_api.replay.run_entry_replay`

## 本地回归

- 默认回归：`pytest`
- 策略契约回归：`pytest tests/strategies/contract -q`
- PostgreSQL 集成回归：先设置 `TRADER_TEST_POSTGRES_DSN`，再运行 `pytest tests/infra/test_postgres_integration.py -q`
- 未设置 `TRADER_TEST_POSTGRES_DSN` 时，PostgreSQL 集成测试会显示为 `skipped`，这是预期行为

## 开发环境数据库说明

- `initialize_database` 只负责按当前源码模型建表，不做历史 schema 迁移。
- 当前仓库没有 Alembic；开发阶段如果 schema 改动不兼容，优先重建开发库后重新执行 `initialize_database`。
- PostgreSQL 仍然只是审计、复盘、调试和恢复参考，不是交易状态唯一真相来源。

## 停止顺序

- 优先停止新买入。
- 等待正在处理的交易主链路订单状态事件完成或进入可 reconcile 状态。
- 停止 scheduler、新的 reconcile 和 market discovery 扫描。
- 停止 strategy worker 和 persistence worker。
- 不要求所有低优先级快照立刻落库，但关键订单审计事件必须留在 outbox。

## 人工操作原则

- 人工操作只通过 Admin API 触发。
- `cancel + replace` 必须先确认原 SELL order 已取消或进入终态，再提交新的 SELL。
- `cancel + replace` 只允许 SELL，不提供 BUY 绕过路径。
- 新 SELL 价格必须满足 market tick size。
- User WS 断线后，需要完成 reconcile 才能恢复新买入。
- 如果账户状态不确定，先全局暂停新买入，再 reconcile。

## 部署变更原则

涉及以下内容的变更需要额外谨慎：
- 交易主链路队列、Order Executor、Risk Manager、Strategy Engine。
- 买入订单类型、卖出价格、预算分配算法。
- WebSocket 重连和 reconcile 恢复策略。
- 数据库 schema 初始化方式和 outbox 格式。
- 新增线程池、进程池、锁、阻塞外部调用。

## 交接记录建议

每次部署至少记录：
- commit id。
- 是否影响交易主链路。
- 是否调整数据库 schema 初始化方式。
- 是否新增配置。
- 是否需要暂停新买入。
- 回滚方式和回滚后的 reconcile 要求。
