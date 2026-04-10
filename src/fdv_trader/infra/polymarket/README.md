# polymarket 目录说明

该目录存放 Polymarket 外部接口适配。

职责：
- Gamma API market / event 元数据读取。
- CLOB orderbook、订单提交、取消和成交查询。
- Data API 持仓和交易数据读取。
- Market WS 与 User WS 连接管理。

约束：
- BUY market order 的 amount 表示 USDC.e 花费金额，SELL 的 amount 表示 shares，需要在适配层明确处理。
- FAK/FOK 不与 post-only 组合。
- 适配层输出系统内部 DTO，不把 SDK 对象泄漏到 Domain 层。

