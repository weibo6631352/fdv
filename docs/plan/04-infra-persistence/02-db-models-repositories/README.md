# 02 DB 模型与 Repository 任务

## 覆盖范围

- 设计文档 `4.2 核心数据模型建议`
- 需求文档 `11. 数据库`
- 设计文档 `2.12 Persistence Worker`

## Worker 任务

- 定义 PostgreSQL / SQLAlchemy 模型：`Market`、`OrderbookSnapshot`、`Allocation`、`Order`、`Fill`、`Position`、`AuditEvent`、`OutboxEvent`。
- 关键表保留 raw JSON 字段，以便适配 Polymarket 响应变化。
- 为审计、订单、成交、持仓和资金分配提供 repository 接口。
- repository 不得被 P0 交易路径直接调用做慢查询；P0 只能通过 outbox 快路径提交持久化请求。
- 写入使用幂等键，例如 `event_type + trace_id + order_id + status`。

## 交付物

- DB 模型字段表和索引建议。
- repository 方法清单：写审计、写 market 快照、写 order、写 fill、写 position、写 allocation、查询 Admin 快照。
- 幂等写入规则。

## 并行接口

- 上游：Persistence Worker、Admin API、启动恢复。
- 下游：PostgreSQL。
- 与 `06-observability-docs/01-audit-trace` 对齐审计字段，与 `04-infra-persistence/04-persistence-worker` 对齐批量写入格式。

## 注释要求

对数据库不是交易状态唯一真相来源、幂等键、raw JSON 字段和 P0 禁止慢查询写中文注释。开发阶段不运行测试。
