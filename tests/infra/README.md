# infra 测试目录说明

该目录存放基础设施适配测试。

重点：
- Polymarket order payload 转换。
- WebSocket 断线重连和 REST 快照校准。
- 数据库失败不阻塞交易提交。
- outbox 幂等和重试。

