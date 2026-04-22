# Codex Rules

本文件整理自仓库内的 `README.md`、`docs/需求文档.md`、`docs/设计文档.md`、`docs/市场发现链路.md` 以及各层 `README`，用于约束 Codex 在本仓库中的改动方式。

只保留跨模块、可长期复用的规则；策略阈值、关键词、仓位参数等易变细节仍以 `src/strategies/current/` 和对应策略文档为准。

## 1. 改动落点

- 改策略规则、筛选语义、定价、仓位和恢复策略，优先改 `src/strategies/current/`。
- 改通用契约、上下文对象和扩展接口，改 `src/polymarket_trader/extension_api/`。
- 改交易编排、恢复编排和管理操作编排，改 `src/polymarket_trader/app/`。
- 改外部 API、数据库、WS、outbox 适配，改 `src/polymarket_trader/infra/`。
- 改运行时状态、调度、队列和 supervisor，改 `src/polymarket_trader/runtime/` 或 `src/polymarket_trader/workers/`。
- 改人工查询和受控操作入口，改 `src/polymarket_trader/api/`。

默认原则：策略差异进策略目录，通用能力进框架；不要为了单个策略需求先改交易主链路。

## 2. 分层边界

依赖方向遵循：

```text
api / workers -> app -> domain
app -> infra / runtime / observability
infra -> domain
runtime -> domain
```

必须遵守：

- Domain 只放纯业务规则、领域模型和内部 DTO，不依赖 FastAPI、SQLAlchemy、Polymarket SDK、WebSocket client、环境变量或数据库查询。
- App 负责用例编排，不保存第二份业务真相，不硬编码某个策略的具体阈值语义。
- Infra 负责外部协议适配，外部 payload 必须先转成内部 DTO 再向上返回。
- Worker 负责搬运消息和调度，不直接实现业务规则，不直接调用 Polymarket SDK。
- API 只做参数校验、调用应用服务和响应序列化，不直接操作交易客户端或运行时热状态写锁。

## 3. 交易链路硬约束

交易订单主链路保持：

```text
event -> TradingDecisionWorker -> TradingDecisionService -> PortfolioAllocator -> RiskManager -> TradingService -> OrderExecutor -> outbox/audit
```

硬约束：

- `OrderExecutor` 是唯一允许创建、签名、提交、取消和替换订单的模块。
- `RiskManager` 是任何下单前的强制门禁；新增下单入口必须显式经过它。
- 业务扩展模块输出框架定义的决策对象，不直接调用交易客户端。
- Admin API 不是自动下单入口，也不是交易客户端直连入口。
- Persistence / outbox / 审计只能异步承接副作用，不能反向阻塞交易主链路。

## 4. 状态真相与运行时优先级

状态真相优先级：

1. Polymarket 实时事件与权威快照
2. 本地内存状态
3. PostgreSQL 审计与快照

执行规则：

- 交易实时判断优先使用内存状态。
- 权威修正依赖 WS 和 REST。
- 数据库只用于审计、复盘、查询和恢复参考，不作为交易唯一真相来源。
- Admin 和 Persistence 读取快照，不直接持有热状态写锁。
- 状态访问按 `condition_id` 或 `token_id` 分片，不使用全局大锁保护全部热状态。
- 非关键锁等待超时后跳过并告警，不能无限等待。

## 5. 并发与性能

- 交易主链路优先级最高。
- 阻塞 I/O 和 CPU 密集任务必须离开交易主事件循环。
- 数据库写入、日志、全量扫描、报表和 Admin 大查询不能反向阻塞 P0 交易路径。
- 交易主链路 worker 不等待后台维护或异步支撑 worker 释放资源。
- Reconciler 不在批量扫描任务中长时间持有交易状态写锁。
- 队列需要容量上限、可观测性和降级路径。

## 6. 结构改造规则

做结构性改造时，优先遵守以下原则：

- 优先一次性切到目标形态，不保留长期双路径。
- 不把关键接线留到后续补丁；主路径所需接线需要在同一轮改动内闭合。
- 不引入只服务过渡期的配置项、状态字段或旁路逻辑。
- 双路径适配层只在明确存在外部契约约束时保留，并且必须记录原因、边界和移除条件。
- 发现调用侧仍使用非目标命名时，优先修改调用侧，不要在框架层长期保留同义字段、别名、包装函数或重复枚举。
- 新增调度器、扫描器或后台任务时，要把运行时状态暴露为可观测快照，便于 supervisor / admin 查询。

## 7. 配置、命名与数据建模

- `.env` 和 `Settings` 只承载框架运行参数；策略参数不应变成框架必填环境变量。
- 策略参数写在策略包内，或通过策略自己的配置加载方式处理。
- 契约字段命名必须单义，避免一套名字对外、一套名字对内的长期双命名层。
- Domain 内金额和价格使用 `Decimal`，不要用浮点数表示交易金额。
- 拒绝原因必须可审计，不能只返回 `False`。
- 策略常量集中管理，避免散落硬编码。

## 8. 测试与文档

- 涉及下单、撤单、成交、持仓、资金分配、风控和 reconcile 的改动，必须补测试。
- 涉及并发、线程池、锁、队列、超时和降级策略的改动，必须补延迟、优先级或恢复测试。
- 测试中应显式模拟数据库慢、日志慢、Admin 查询慢、低优先级队列积压和 WS 重连。
- 测试不能依赖真实 Polymarket 账户、生产数据库或真实私钥。
- 新增接口、配置项、运行时状态或人工操作入口时，同步更新对应文档。

## 9. 常见误区

- 在 route 里写交易逻辑。
- 在 worker 里复制 discovery / 扩展业务判断。
- 在 framework 层加入当前业务扩展专属字段或阈值。
- 为了减少改动，在 Domain 或内部接口中保留长期同义命名。
- 让数据库、持久化、日志或报表路径决定交易热路径是否能继续运行。
