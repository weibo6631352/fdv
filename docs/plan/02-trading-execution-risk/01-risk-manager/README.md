# 01 Risk Manager 任务

## 覆盖范围

- 设计文档 `2.6 Risk Manager`
- 需求文档 `9. 风控`
- 设计文档 `3.3 Orderbook 监听与入场信号流程`

## Worker 任务

- 在任何下单前执行强制风控检查，返回 `RiskCheckPassed` 或 `RiskCheckFailed`，不直接提交订单。
- 检查分类必须是 Crypto + FDV + 500M。
- 检查 market 必须 active、open、CLOB enabled、未 resolved / cancelled / archived。
- 检查 `NO best ask <= entry_no_price_max`，price 符合 `tick_size`，notional 满足 `min_order_size`。
- 检查单笔、单 market、策略总投入、open orders 数量、spread、流动性、重试次数、余额、allowance 和地理限制。
- 识别买入侧长期 open BUY 异常，并输出必须 cancel 的风险原因。
- 下单前只读取本地热状态和已同步快照，不在 P0 路径临时发起慢 REST 查询或数据库查询。

## 交付物

- 风控输入 DTO：`OrderIntent`、`AllocationPlan`、market / orderbook / position / open orders 快照、runtime config。
- 结构化失败原因，例如 `not_crypto_fdv_500m`、`price_above_entry_max`、`tick_size_invalid`、`min_order_not_met`、`market_limit_reached`、`total_limit_reached`、`open_buy_detected`、`allowance_insufficient`。
- 风控结果必须包含 `trace_id`、检查项、失败字段、建议动作和是否可重试。

## 并行接口

- 上游：Strategy Engine 和 Portfolio Allocator。
- 下游：Order Executor、Audit Logger、StrategySkipped。
- 与 `04-infra-persistence/05-config-secrets` 对齐全部风控配置字段。

## 注释要求

对每个强制门禁的业务原因、不得发起慢查询的原因、open BUY 风险和地理/allowance/余额检查来源写中文注释。开发阶段不要求补充或运行验证测试。

