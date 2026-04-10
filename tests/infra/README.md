# infra 测试目录说明

该目录存放基础设施适配测试。这里验证外部协议转换、数据库仓储、outbox 和 WebSocket 行为。

## 覆盖范围

- Polymarket Gamma / CLOB / Data API 响应到内部 DTO 的转换。
- FAK BUY 和 GTC SELL payload 字段语义。
- BUY `amount` 表示 USDC.e 花费金额，SELL `amount` 表示 shares。
- WebSocket 断线重连和 REST 快照校准。
- 数据库失败不阻塞交易提交。
- outbox 幂等键、重试次数和最后错误。
- 仓储分页和索引字段。

## 必须保持的边界

- 默认使用 fake server、mock transport 或本地测试数据库。
- 不使用生产 API key、私钥或真实钱包。
- 不把 SDK 原始对象泄漏到 domain 断言之外。
- 对外部调用超时、重试和错误类型做断言。

## 新增测试交接清单

新增 infra adapter 时，需要测试：
- 成功响应转换。
- 失败响应转换。
- 超时和重试边界。
- 脱敏日志或审计摘要。
- 与 domain DTO 的兼容性。

