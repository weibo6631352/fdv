# app 目录说明

该目录存放应用服务和用例编排。

职责：
- 组合 domain 与 infra 能力。
- 编排 market 发现、reconcile、交易流程和 Admin 操作。
- 将外部请求转化为明确的业务用例。

约束：
- 不直接拼接 Polymarket 原始 payload。
- 不把 HTTP handler 或数据库模型传入 Domain 层。

