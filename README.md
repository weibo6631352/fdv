# Polymarket FDV 自动交易系统

本仓库用于实现面向 Polymarket Crypto / FDV / 500M markets 的自动交易系统。系统目标不是做通用交易框架，而是围绕明确策略边界构建一个可审计、可恢复、不会让低优先级任务拖慢交易链路的生产服务。

业务约束以 [需求文档](./docs/需求文档.md) 和 [设计文档](./docs/设计文档.md) 为准。任何实现、重构和测试都必须保持这些约束不被削弱。

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

## 开发规划与项目组分工

详细并行开发任务见 [docs/plan](./docs/plan/README.md)。

阶段说明：
- 开发过程中不运行测试，验证测试由专项验收阶段统一安排。
- 开发交付以模块边界、核心逻辑、审计字段、配置项、注释规范和文档同步为主要检查项。
- 如果开发过程中发现需求、设计或文档存在遗漏、歧义、不合理约束或明显 bug，需要及时反馈并推动对齐；设计本身也可能有未覆盖的场景，鼓励提出更好的实现建议并交流确认。
- 为阶段性开发或验证临时增加的测试专用接口、调试入口和旁路逻辑，在测试通过或阶段任务完成后应及时删除，避免残留到正式实现中增加复杂度。
- 如果确实需要为测试扩展能力，优先在 `tests` 目录通过 fixture、stub、fake 或测试辅助代码扩展；不要在 `src` 源码中直接暴露测试专用接口，除非确有必要且已说明原因与后续清理方式。
- 代码注释必须解释关键业务规则、状态不变量、异常降级策略和 P0 / P1 / P2 / P3 优先级原因，避免描述语法本身或留下过期 TODO。

| 项目组 | 优先级 | 开发清单 | 交付关注点 |
| --- | --- | --- | --- |
| 策略与领域模型组 | P0 | 实现 market 分类、FDV / 500M 匹配、等权资金分配、价格触发、订单状态机和风险敞口计算 | Domain 层不依赖外部 SDK；规则常量命名清晰；对拒绝原因、分配结果和风险失败原因保留结构化字段 |
| 交易执行与风控组 | P0 | 实现 Risk Manager、Order Executor、FAK BUY、GTC SELL、异常 open BUY cancel、cancel / replace 和成交后卖单补挂 | Order Executor 保持唯一交易入口；下单前必须经过风控；注释说明订单类型、价格上限和异常处理原因 |
| 实时数据与运行时组 | P0 / P1 | 实现 Market WS、User WS、orderbook cache、事件总线、优先级队列、scheduler、supervisor 和断线重连 | P0 队列与低优先级任务隔离；锁粒度按 market / token 分片；注释说明背压、重连和快照校准策略 |
| 基础设施与持久化组 | P1 / P3 | 实现 Polymarket API 适配、数据库模型、repository、outbox、本地可靠队列和 Persistence Worker | 外部响应统一转换为内部 DTO；数据库写入不得阻塞交易主流程；审计 raw response 注意脱敏 |
| Admin API 与运维组 | P2 / P3 | 实现健康检查、market / portfolio / order 查询、人工 cancel / replace 入口、配置文档和 runbook | Admin API 只能调用应用服务；查询读取快照并限流分页；人工操作必须保留 trace_id 和审计记录 |
| 可观测与文档规范组 | P1 / P3 | 实现结构化日志、指标、trace、审计事件字段、README 和 docs 同步维护 | 交易延迟指标覆盖关键时间点；文档术语与源码模块一致；注释和文档不记录密钥、签名 payload 或未脱敏账户信息 |

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
- [需求文档](./docs/需求文档.md) 第 4 到 13 节。
- [设计文档](./docs/设计文档.md) 第 1、2、4、5 节。

提交改动前，需要确认：
- 是否影响 P0 交易链路。
- 是否新增锁、队列、线程池、进程池或外部调用。
- 是否新增数据库查询或日志写入进入交易热路径。
- 是否改变 FAK BUY、GTC SELL、等权分配、reconcile 或 open BUY 异常处理。
- 是否按当前阶段说明确认：开发过程中不运行测试，验证测试由专项验收阶段统一安排。
- 是否补充或确认了对应审计字段，并按注释规范解释关键业务规则与异常处理原因。
