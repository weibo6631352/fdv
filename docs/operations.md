# 运维说明

该文档用于记录部署、启动、停止、升级和人工操作约定。运维动作的首要目标是保持交易状态可确认、可恢复，而不是强行让服务继续下单。

## 初始启动顺序

1. 准备环境变量，确认密钥不在仓库内。
2. 准备 PostgreSQL，并执行 Alembic 迁移。
3. 启动服务，检查 `/health`。
4. 初始化 outbox、数据库连接、Polymarket clients 和运行时队列。
5. 拉取 Gamma / CLOB / Data API 权威快照。
6. 完成首次 reconcile。
7. 确认余额、allowance、User WS 和 Market WS 状态正常。
8. 允许策略进入自动下单状态。

## 停止顺序

- 优先停止新买入。
- 等待正在处理的 P0 订单状态事件完成或进入可 reconcile 状态。
- 记录停止审计事件。
- 停止 WS worker、strategy worker、reconcile worker 和 persistence worker。
- 不要求所有低优先级快照立刻落库，但关键订单审计事件必须留在 outbox。

## 人工操作原则

- 人工操作只通过 Admin API / CLI 触发。
- `cancel + replace` 必须先确认原 SELL order 已取消或进入终态，再提交新的 SELL。
- User WS 断线后，需要完成 reconcile 才能恢复新买入。
- 如果账户状态不确定，先全局暂停新买入，再 reconcile。

## 部署变更原则

涉及以下内容的变更需要额外谨慎：
- P0 交易队列、Order Executor、Risk Manager、Strategy Engine。
- 买入订单类型、卖出价格、预算分配算法。
- WebSocket 重连和 reconcile 恢复策略。
- 数据库迁移和 outbox 格式。
- 新增线程池、进程池、锁、阻塞外部调用。

## 交接记录建议

每次部署至少记录：
- commit id。
- 是否影响 P0 交易链路。
- 是否新增迁移。
- 是否新增配置。
- 是否需要暂停新买入。
- 回滚方式和回滚后的 reconcile 要求。

