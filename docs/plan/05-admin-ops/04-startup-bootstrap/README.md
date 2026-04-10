# 04 启动恢复任务

## 覆盖范围

- 设计文档 `3.1 系统启动流程`
- 设计文档 `1.6 状态真相来源`
- 设计文档 `3.10 高优先级交易事件处理流程`

## Worker 任务

- 按顺序加载配置和密钥，检查必填项。
- 初始化日志、指标、outbox、数据库连接和 Polymarket clients。
- 初始化 P0 `TradingEventQueue`、专用 `trading_thread_pool`、P2 / P3 维护队列和线程池 / 进程池。
- 执行地理限制、余额、allowance、API credential 检查。
- 从 PostgreSQL 加载最近 target markets、orders、positions 作为恢复参考。
- 调用 Gamma / CLOB / Data API 拉取权威快照。
- 用权威快照覆盖本地过期状态，标记不一致项并写审计日志。
- 启动 Market Discovery、Market WS、User WS、Reconciler、Persistence Worker。
- 首次 reconcile 完成前禁止策略自动下单。

## 交付物

- 启动状态机：config_loading、infra_ready、recovering_snapshot、reconciling、workers_started、trading_enabled、degraded。
- 启动失败原因和降级策略。
- 自动下单开关的单一来源。

## 并行接口

- 上游：main / CLI。
- 下游：config、infra clients、runtime queues、workers、reconcile、observability。
- 与 `03-realtime-runtime/06-scheduler-supervisor-recovery` 对齐恢复状态和 supervisor 降级。

## 注释要求

对状态真相来源、权威快照覆盖、首次 reconcile 前禁自动下单和启动失败降级写中文注释。开发阶段不运行测试。

