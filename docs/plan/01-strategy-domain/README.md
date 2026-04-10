# 策略与领域模型组

## 目标

负责不依赖外部 SDK、数据库、FastAPI 或环境变量的纯业务规则层。该组产出稳定 DTO、事件、分类、分配、策略状态机和领域状态结构，供交易执行、运行时、持久化和 Admin 查询共同使用。

## 可并行任务

| 任务 | Worker 入口 | 主要模块 |
| --- | --- | --- |
| Market 分类 | [01-market-classifier](./01-market-classifier/README.md) | `src/fdv_trader/domain/classifier.py` |
| Market Registry 与模型 | [02-market-registry-models](./02-market-registry-models/README.md) | `src/fdv_trader/domain/market.py`、`src/fdv_trader/runtime/registry.py` |
| 资金分配 | [03-portfolio-allocation](./03-portfolio-allocation/README.md) | `src/fdv_trader/domain/allocation.py` |
| 策略引擎与状态机 | [04-strategy-engine-state-machine](./04-strategy-engine-state-machine/README.md) | `src/fdv_trader/domain/strategy.py`、`src/fdv_trader/domain/state_machine.py` |
| 领域 DTO 与事件契约 | [05-domain-dto-events](./05-domain-dto-events/README.md) | `src/fdv_trader/domain/events.py`、`order.py`、`position.py`、`orderbook.py` |

## 并行边界

- 分类、分配、策略状态机可以并行开发，但必须先对齐 `Market`、`OrderIntent`、`AllocationPlan`、`RiskCheckResult`、`DomainEvent` 的字段名。
- 本组不得引入 Polymarket SDK 对象、SQLAlchemy 模型、FastAPI request/response 或环境变量读取。
- 注释重点写清 FDV / 500M 规则、阈值排除、等权分配不变量、FAK 资金释放和状态转换原因。
- 开发阶段不要求补充或运行验证测试；涉及测试重点的内容记录到验收测试计划。

