# tests 目录说明

该目录存放测试。

分层：
- [domain](./domain/README.md)：分类、分配、风控和策略规则测试。
- [app](./app/README.md)：交易流程、reconcile 和服务编排测试。
- [infra](./infra/README.md)：Polymarket 适配、订单执行和 WS 重连测试。

重点：
- 交易规则和风控优先覆盖。
- 并发、队列、锁和超时相关改动必须补测试。
- 数据库慢、日志慢、Admin 查询慢和 WS 重连需要显式模拟。

