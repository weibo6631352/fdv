# 05 故障处置 Runbook 任务

## 覆盖范围

- 设计文档 `3.9 异常处理流程`
- `docs/runbook.md`
- `docs/operations.md`

## Worker 任务

- 为 Market WS 断线编写处置：指数退避重连，重连后 REST 快照校准。
- 为 User WS 断线编写处置：暂停新买入，重连并完成订单/持仓 reconcile 后恢复。
- 为 Gamma API 拉取失败编写处置：保留已有 markets，延迟重试，不新增未知 market。
- 为 CLOB 下单失败编写处置：记录错误，按 retry limit 控制重试。
- 为 DB 写入失败编写处置：outbox 保留，Persistence Worker 重试。
- 为余额或 allowance 不足编写处置：暂停新买入，Admin API 暴露告警。
- 为买入订单进入 live 编写处置：立即 cancel，暂停该 market，写异常审计。
- 为 market resolved / closed 编写处置：停止买入，取消或保留 SELL 按风控配置处理。
- 为低优先级任务阻塞编写处置：暂停或限速 P2 / P3，P0 交易队列继续运行。
- 为交易锁等待超时编写处置：跳过非关键状态写入并告警；关键订单状态进入 P0 修复流程。

## 交付物

- runbook 故障矩阵：触发条件、影响范围、自动动作、人工动作、恢复条件、审计事件。
- operations 流程更新：暂停/恢复、人工 cancel + replace、reconcile、告警响应。
- 故障优先级 P0 / P1 / P2 / P3 标注。

## 并行接口

- 上游：Supervisor、metrics、Admin API 告警。
- 下游：运维人员和人工操作入口。
- 与 `06-observability-docs/02-metrics-alerts` 对齐告警名称与阈值。

## 注释要求

本任务主要产出文档；若涉及代码注释，对自动降级、人工介入条件和恢复条件写中文说明。开发阶段不运行测试。

