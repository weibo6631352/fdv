# 06 Scheduler / Supervisor / Recovery 任务

## 覆盖范围

- 设计文档 `1.5 运行时组件`
- 设计文档 `3.9 异常处理流程`
- 设计文档 `1.7 高性能与交易优先级设计`

## Worker 任务

- 管理 Market Discovery、Market WS、User WS、Strategy Worker、Reconciler、Persistence Worker 和 Admin API 的启动、停止和健康状态。
- 支持生产环境优先启用 `uvloop`，不可用时回退标准事件循环。
- 为同步 SDK 调用、订单签名、阻塞文件 I/O、轻量 CPU 工作配置受控线程池。
- 对批量分类、历史回放、报表生成等 CPU 密集非交易任务使用进程池或独立进程隔离。
- 监控 P0 队列积压、锁等待、执行器排队和订单提交延迟；超过阈值时暂停或限速 P2 / P3 任务。
- 处理异常：Market WS 断线重连、User WS 断线暂停新买入、Gamma API 拉取失败延迟重试、DB 写入失败交给 outbox、低优先级任务阻塞限速、交易锁等待超时告警。
- 统一恢复策略：权威快照覆盖本地过期状态，恢复完成前禁止自动下单。

## 交付物

- Scheduler 任务注册和周期调度策略。
- Supervisor 降级策略与 worker 健康状态模型。
- 恢复状态机：starting、recovering、reconciling、trading_enabled、paused、degraded。

## 并行接口

- 依赖 Event Bus 指标、worker 健康检查、配置项和 observability。
- 与 `05-admin-ops/04-startup-bootstrap` 对齐启动阶段顺序。
- 与 `06-observability-docs/02-metrics-alerts` 对齐告警阈值和指标名。

## 注释要求

对低优先级限速、User WS 断线暂停新买入、恢复完成前禁止自动下单和线程池/进程池隔离写中文注释。开发阶段不要求补充或运行验证测试。

