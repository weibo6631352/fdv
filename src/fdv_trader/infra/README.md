# infra 目录说明

该目录存放外部系统适配和技术设施。

职责：
- Polymarket Gamma / CLOB / Data / WS 适配。
- PostgreSQL 数据库访问。
- outbox 可靠事件队列。
- 时间、序列化、外部 I/O 等基础设施。

约束：
- infra 可以依赖外部 SDK，但需要转换为系统内部 DTO。
- 阻塞 I/O 不得直接进入 P0 交易事件循环。

