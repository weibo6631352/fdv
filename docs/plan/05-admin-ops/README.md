# Admin API 与运维组

## 目标

负责 Admin API、CLI、健康检查、人工操作、启动恢复和运维故障处置。该组只能通过应用服务和快照读取系统状态，不能绕过风控或直接阻塞交易热状态。

## 可并行任务

| 任务 | Worker 入口 | 主要模块 |
| --- | --- | --- |
| Admin 只读查询 API | [01-admin-readonly-api](./01-admin-readonly-api/README.md) | `src/fdv_trader/api/routes`、`app/admin_service.py` |
| Admin cancel + replace | [02-admin-cancel-replace](./02-admin-cancel-replace/README.md) | `src/fdv_trader/api/routes/orders.py`、`app/admin_service.py` |
| CLI / health / operations | [03-cli-health-operations](./03-cli-health-operations/README.md) | `src/fdv_trader/cli`、`api/routes/health.py` |
| 启动恢复 | [04-startup-bootstrap](./04-startup-bootstrap/README.md) | `src/fdv_trader/main.py`、`runtime`、`workers` |
| 故障处置 runbook | [05-runbook-failure-ops](./05-runbook-failure-ops/README.md) | `docs/operations.md`、`docs/runbook.md` |

## 并行边界

- Admin API 查询必须分页、限流并读取快照或仓储数据，不得持有交易热状态写锁。
- 人工 cancel + replace 只能操作 SELL，不能提供绕过 Risk Manager 的 BUY 下单入口。
- 启动恢复完成权威快照和首次 reconcile 前，自动下单必须保持禁用。
- 运维文档需要明确暂停/恢复、告警、故障优先级和人工操作审计。

