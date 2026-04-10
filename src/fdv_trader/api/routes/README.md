# routes 目录说明

该目录存放 Admin API 的路由模块。

职责：
- 按资源拆分 HTTP endpoint。
- 将请求转换为应用服务调用。
- 统一返回适合人工查询和运维使用的数据。

约束：
- 路由层不直接访问 Polymarket SDK。
- 路由层不持有交易状态写锁。

