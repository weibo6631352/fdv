# domain 目录说明

该目录存放纯业务规则、领域模型和内部 DTO。Domain 层必须能在没有数据库、没有 FastAPI、没有 Polymarket SDK、没有 WebSocket 的情况下独立测试。

## 职责

- Market 分类规则：Crypto 分类、FDV event、500M threshold、排除非目标阈值。
- 资金分配规则：eligible markets、等权预算、剩余额度、FAK 释放资金再分配。
- 风控规则：单笔、单 market、组合、open orders、价格、spread、流动性和重试限制。
- 策略规则：入场、FAK 成交处理、GTC SELL 意图、跳过原因。
- 领域模型：market、orderbook、order、fill、position、allocation、events、状态机。

## 文件职责

- `allocation.py`：组合资金分配模型和算法。
- `classifier.py`：market 文本与分类规则。
- `constants.py`：策略常量，例如 `0.60` 和 `0.70`。
- `events.py`：领域事件模型。
- `market.py`：market 元数据和交易状态。
- `order.py`：订单意图、方向、类型和状态。
- `orderbook.py`：orderbook 快照、价格层级和 spread。
- `position.py`：持仓与 open SELL 覆盖状态。
- `risk.py`：下单前风控门禁。
- `strategy.py`：从策略条件生成订单意图。
- `state_machine.py`：market / 交易生命周期。

## 允许依赖

- Python 标准库。
- 与业务建模相关的轻量纯 Python 库。
- 同层 domain 模块。

## 禁止依赖

- FastAPI、SQLAlchemy、Alembic。
- Polymarket SDK、HTTP client、WebSocket client。
- 环境变量、配置加载、日志落盘、数据库查询。
- runtime registry、worker、app service。

## 接口契约

- Domain 输入应是内部 DTO、dataclass、枚举、Decimal 或基础类型。
- Domain 输出应是决策对象、意图对象、事件对象或错误原因。
- 拒绝原因必须可审计，不能只返回 `False`。
- 金额和价格使用 `Decimal`，不要用浮点数表示交易金额。
- 策略常量需要集中管理，避免散落硬编码。
- 契约字段和类型名必须有明确业务语义；不要为了兼容旧调用面、让测试临时通过或减少改动而新增别名、包装函数、重复枚举或同义字段。
- 可以保留只读派生属性，例如事件的 `name` 从 `event_type` 派生、`occurred_at` 从 `created_at` 派生；派生属性不得持有第二份状态，也不得改变统一字段名。
- 发现调用侧仍使用旧名字时，优先修改调用侧对齐当前契约；只有在设计文档明确要求对外兼容时，才允许新增兼容层，并需要在对应 README 中写明原因、边界和移除条件。

## 交接清单

修改 Domain 前确认：
- 是否改变业务策略或风控规则。
- 是否新增拒绝原因和审计字段。
- 是否补充 domain 单元测试。
- 是否影响 App 层调用契约。
- 是否保持纯函数 / 纯模型可测试性。
- 是否引入了非设计内兼容层、旧字段别名或重复命名入口；如果有，先删除或记录明确设计理由。
