# versions 目录说明

该目录存放 Alembic 生成的版本化迁移脚本。这里的每个文件都应该对应一次明确的 schema 变更。

## 命名建议

- 使用 Alembic 默认 revision id。
- message 使用可搜索的英文短语，例如 `create_audit_events`、`add_order_idempotency_key`。

## 迁移内容边界

允许：
- 创建、修改、删除表和索引。
- 增加幂等键、审计字段、状态字段和 raw JSON 摘要字段。
- 为查询和排障增加必要索引。

禁止：
- 写入生产数据。
- 写入密钥或未脱敏样例。
- 调用外部 API。
- 在迁移中实现业务规则。

## Review 清单

提交前确认：
- upgrade 和 downgrade 路径是否符合预期。
- 是否影响已有审计事件写入。
- 是否影响 Persistence Worker 幂等写入。
- 是否需要同步更新数据库模型、仓储、测试和 docs。

