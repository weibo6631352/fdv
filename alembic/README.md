# alembic 目录说明

该目录存放 PostgreSQL 数据库迁移脚本。数据库用于审计、复盘、调试和恢复参考，不是订单、成交和持仓状态的唯一真相来源。

## 职责

- 管理 market、orderbook snapshot、allocation、order、fill、position、audit event 和 outbox 相关表结构。
- 记录 schema 的版本化变更。
- 支持部署时可重复执行迁移。

## 允许依赖

- Alembic。
- SQLAlchemy metadata。
- 与迁移相关的标准库工具。

## 禁止事项

- 在迁移中写入生产密钥、私钥、账户地址或未脱敏 raw response。
- 在迁移中调用 Polymarket API。
- 把数据库设计成交易状态唯一真相来源。
- 为了方便查询而反向要求 P0 交易链路同步等待数据库写入。

## 迁移设计原则

- 审计表保留 `trace_id`、事件类型、时间、状态和必要 raw JSON 摘要字段。
- 订单、成交、持仓表需要支持幂等写入。
- outbox 表需要支持重试次数、最后错误、幂等键和状态。
- 大 raw response 需要限长或拆低优先级存储。

## 交接清单

新增迁移时，需要说明：
- 影响哪些应用模块。
- 是否需要停机或暂停新买入。
- 是否改变 outbox / audit 事件格式。
- downgrade 是否可用；如果不可用，需要写明原因。

