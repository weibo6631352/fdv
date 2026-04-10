# fdv_trader 包说明

该包是 Polymarket FDV 自动交易系统的主源码包。

分层：
- [api](./api/README.md)：Admin API 与健康检查。
- [cli](./cli/README.md)：命令行入口。
- [app](./app/README.md)：应用用例编排。
- [domain](./domain/README.md)：纯业务规则。
- [infra](./infra/README.md)：外部系统适配。
- [observability](./observability/README.md)：审计、指标和 trace。
- [runtime](./runtime/README.md)：事件总线、状态注册表和运行时控制。
- [workers](./workers/README.md)：常驻后台任务。

边界原则：
- Domain 不依赖 HTTP、数据库或 Polymarket SDK。
- Order Executor 是唯一提交、取消、替换订单的模块。
- Risk Manager 是下单前强制门禁。

