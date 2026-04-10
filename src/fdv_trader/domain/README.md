# domain 目录说明

该目录存放纯业务规则。

职责：
- market 分类、资金分配、风控、策略判断、订单和持仓领域模型。
- 维护与 Polymarket SDK 解耦的内部 DTO 和状态机。

约束：
- 不依赖 FastAPI、SQLAlchemy、WebSocket client 或 Polymarket SDK。
- 不发起网络请求或数据库查询。
- 交易规则变更需要优先补充单元测试。

