# 可观测与文档规范组

## 目标

负责审计链路、trace、metrics、结构化日志、敏感信息脱敏、文档规范、注释规范和验收测试计划。该组为其他项目组提供统一事件名、字段名和检查清单。

## 可并行任务

| 任务 | Worker 入口 | 主要模块 |
| --- | --- | --- |
| Audit / Trace | [01-audit-trace](./01-audit-trace/README.md) | `src/fdv_trader/observability/audit.py`、`trace.py` |
| Metrics / Alerts | [02-metrics-alerts](./02-metrics-alerts/README.md) | `src/fdv_trader/observability/metrics.py` |
| Logging / Redaction | [03-logging-redaction](./03-logging-redaction/README.md) | `src/fdv_trader/logging.py` |
| 文档与注释规范 | [04-docs-comments](./04-docs-comments/README.md) | `docs`、各目录 README |
| 验收测试计划 | [05-acceptance-test-plan](./05-acceptance-test-plan/README.md) | `tests` 目录规划，不要求开发阶段执行 |

## 并行边界

- 审计事件名、trace 字段和 metrics 名称需要先发布契约，供其他 worker 引用。
- 日志和 raw response 必须做长度限制与敏感信息脱敏。
- 文档和注释规范不替代业务实现，但对 P0 并发、风控、订单语义和异常降级的解释必须可审计。
- 开发阶段不要求补充或运行验证测试；本组只维护验收阶段的测试覆盖计划。

