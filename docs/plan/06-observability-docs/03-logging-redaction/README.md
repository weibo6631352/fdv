# 03 Logging / Redaction 任务

## 覆盖范围

- 设计文档 `1.7 高性能与交易优先级设计`
- 设计文档 `5.1 编码与文件格式`
- 设计文档 `5.2 中文注释规范`

## Worker 任务

- 日志系统必须异步化，交易路径只能提交结构化日志事件，不同步等待日志落盘。
- 统一结构化日志字段：`trace_id`、`event_type`、`priority`、`market_slug`、`condition_id`、`token_id`、`order_id`、`status`、`reason`、`latency_ms`。
- 对 Polymarket API key / secret / passphrase、wallet private key、signer 配置、builder attribution credentials、数据库密码、签名 payload 和未脱敏账户信息做脱敏。
- raw response 记录长度限制，必要时保留摘要和字段白名单。
- 错误日志区分可重试、不可重试、需要人工介入和进入 reconcile 校准。
- 文档和注释中也不得出现密钥、完整签名 payload 或未脱敏 raw response。

## 交付物

- logging 配置和脱敏过滤器。
- 敏感字段黑名单 / 白名单。
- 日志等级和错误分类规范。

## 并行接口

- 上游：所有需要记录日志的 worker。
- 下游：Audit Logger、Persistence Worker、runbook。
- 与 `04-infra-persistence/05-config-secrets` 对齐敏感配置字段名。

## 注释要求

对为什么 P0 不同步落盘、哪些字段必须脱敏、raw response 摘要策略写中文注释。开发阶段不运行测试。

