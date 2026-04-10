# 03 CLI / Health / Operations 任务

## 覆盖范围

- 设计文档 `2.13 Admin API / CLI`
- 设计文档 `1.5 运行时组件`
- `docs/operations.md`

## Worker 任务

- 提供命令行入口，用于启动服务、查看配置摘要、触发受控 reconcile、查看运行状态。
- 提供 `GET /health`，只覆盖进程状态和本地轻量检查，不访问慢外部依赖。
- 提供 `GET /ready`，通过快照或轻量依赖状态覆盖配置加载、DB 可用性、Polymarket client 可用性、WS 状态、outbox 积压和是否允许自动下单。
- 健康检查不得触发慢查询或持有交易热状态写锁。
- operations 文档需要说明启动、停止、reconcile、人工操作和部署流程。
- CLI 只能调用应用服务，不能直接操作订单执行器或热状态。

## 交付物

- CLI 命令清单。
- `/health`、`/ready` 或等价健康检查语义说明。
- operations 文档更新点。

## 并行接口

- 上游：运维人员和部署脚本。
- 下游：runtime registry、scheduler、supervisor、repository 快照。
- 与 `05-admin-ops/04-startup-bootstrap` 对齐启动阶段状态。

## 注释要求

对健康检查不触发慢路径、CLI 不绕过应用服务和 readiness 与自动下单状态差异写中文注释。开发阶段不运行测试。
