# 05 领域 DTO 与事件契约任务

## 覆盖范围

- 设计文档 `1.4 分层设计`
- 设计文档 `4.2 核心数据模型建议`
- 需求文档 `10. 审计日志`

## Worker 任务

- 定义系统内部 DTO，隔离 Polymarket SDK、WebSocket raw payload、SQLAlchemy 模型和 FastAPI schema。
- 覆盖核心模型：`Market`、`OrderbookSnapshot`、`Allocation`、`Order`、`Fill`、`Position`、`AuditEvent`、`OutboxEvent`。
- 定义领域事件基础字段：`trace_id`、`event_type`、`event_id`、`market_slug`、`condition_id`、`token_id`、`reason`、`created_at`。
- 定义订单字段：`side`、`order_type`、`price`、`size`、`amount`、`notional_usdc`、`order_id`、`trade_id`、`status`。
- 定义幂等相关字段，供 Order Executor、outbox、Persistence Worker 共用。
- 提供 DTO 版本兼容策略，避免外部 API 字段变化直接扩散到 domain。

## 交付物

- 统一 DTO / 事件字段表。
- 事件命名建议：`market_discovered`、`market_filtered_in`、`market_filtered_out`、`entry_signal_triggered`、`risk_check_passed`、`risk_check_failed`、`order_created`、`order_signed`、`order_submitted`、`order_matched`、`order_no_fill`、`order_partially_filled`、`exit_order_submitted`、`order_cancel_requested`、`order_cancelled`、`replace_order_submitted`、`trade_confirmed`、`skipped`、`error`。
- 与 DB 模型、Admin schema、审计事件保持可映射但不互相依赖。
- 契约只能保留设计内字段、类型和有明确语义的只读派生属性；不得为了旧调用面或测试通过新增同义别名、包装工厂、重复枚举或第二套事件名。
- 如果测试或调用方仍依赖旧名字，应修改调用方对齐统一契约；确需兼容外部协议时，兼容层必须留在 adapter / schema 边界，不得扩散进 domain DTO。

## 并行接口

- 本任务是全组共享契约，建议优先交付。
- `04-infra-persistence/01-polymarket-clients-schemas` 负责 raw payload 到 DTO 的转换。
- `06-observability-docs/01-audit-trace` 负责审计字段扩展和 trace 传播规范。

## 注释要求

对 BUY `amount` 与 SELL `size` / shares 语义差异、内部 DTO 与外部协议隔离原因写中文注释。开发阶段不运行测试。
