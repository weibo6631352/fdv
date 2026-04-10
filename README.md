# Polymarket FDV 自动交易系统

本仓库用于实现面向 Polymarket Crypto / FDV / 500M markets 的自动交易系统。系统目标不是做通用交易框架，而是围绕明确策略边界构建一个可审计、可恢复、不会让低优先级任务拖慢交易链路的生产服务。

业务约束以 [需求文档](./需求文档.md) 和 [设计文档](./设计文档.md) 为准。任何实现、重构和测试都必须保持这些约束不被削弱。

## 核心规则

- 只交易 Crypto 分类下，event 命中 FDV，market 命中 500M 阈值的目标 market。
- 买入标的是 `NO outcome token`。
- 买入只允许 `FAK BUY`，买入价格上限为 `0.60`。
- 买入侧不得保留长期 resting BUY order；一旦发现 open BUY 异常，必须立即进入 cancel / reconcile 修复流程。
- 买入成交后，只对实际成交 shares 挂 `GTC SELL at 0.70`。
- 资金按 eligible markets 尽量等权分配，FAK 未成交资金必须释放并重新进入分配流程。
- 数据库用于审计、复盘、调试和恢复参考，不作为交易状态唯一真相来源。
- 交易链路 P0 优先级最高，不得被 Admin 查询、数据库写入、日志落盘、全量 market 扫描、报表或低优先级 reconcile 阻塞。

## 架构分层

代码采用 `src` layout，主包是 [src/fdv_trader](./src/fdv_trader/README.md)。

| 层级 | 目录 | 主要职责 |
| --- | --- | --- |
| Interfaces | [api](./src/fdv_trader/api/README.md)、[cli](./src/fdv_trader/cli/README.md) | Admin API、健康检查、命令行入口 |
| Application | [app](./src/fdv_trader/app/README.md) | 用例编排，组合 domain 与 infra |
| Domain | [domain](./src/fdv_trader/domain/README.md) | 分类、分配、风控、策略、订单和持仓规则 |
| Infrastructure | [infra](./src/fdv_trader/infra/README.md) | Polymarket、数据库、outbox 和外部 I/O 适配 |
| Observability | [observability](./src/fdv_trader/observability/README.md) | 审计、trace、指标 |
| Runtime | [runtime](./src/fdv_trader/runtime/README.md) | 事件总线、状态注册表、调度、supervisor |
| Workers | [workers](./src/fdv_trader/workers/README.md) | 常驻后台任务 |
| Tests | [tests](./tests/README.md) | 单元、编排和基础设施测试 |

## 模块接口原则

- Domain 层只能使用系统内部 DTO，不依赖 FastAPI、SQLAlchemy、Polymarket SDK、WebSocket client 或环境变量。
- App 层负责编排用例，不直接拼接 Polymarket payload，不绕过 Domain 的规则对象。
- Infra 层负责外部协议适配，必须把 Polymarket / DB / WS 的响应转换为内部 DTO 后再向上返回。
- Order Executor 是唯一允许创建、签名、提交、取消和替换订单的模块。
- Risk Manager 是任何下单前的强制门禁。新增下单入口必须显式经过 Risk Manager。
- Admin API / CLI 只能调用应用服务，不能直接碰交易热状态写锁，不能绕过风控。
- Persistence Worker 和数据库写入只能异步承接 outbox 事件，不能反向阻塞 P0 交易流程。

## 交接清单

接手任何模块前，先阅读：
- 本文件。
- 对应目录的 `README.md`。
- [需求文档](./需求文档.md) 第 4 到 13 节。
- [设计文档](./设计文档.md) 第 1、2、4、5 节。

提交改动前，需要确认：
- 是否影响 P0 交易链路。
- 是否新增锁、队列、线程池、进程池或外部调用。
- 是否新增数据库查询或日志写入进入交易热路径。
- 是否改变 FAK BUY、GTC SELL、等权分配、reconcile 或 open BUY 异常处理。
- 是否补充了对应测试和审计字段。

