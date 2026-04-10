# 03 组合资金分配任务

## 覆盖范围

- 设计文档 `2.5 Portfolio Allocator`
- 设计文档 `3.6 资金再分配流程`
- 需求文档 `8. 组合资金分配`

## Worker 任务

- 实现 `equal_weight` 分配：`portfolio_budget_usdc / eligible_market_count`。
- eligible market 过滤必须包含分类通过、可交易、`NO best ask <= 0.60`、流动性通过、spread 通过、风控未触顶。
- 计算 `current_exposure`，包含已成交持仓成本、pending BUY、open SELL 对应底层持仓成本。
- 每个 market 可买额度取 `target_market_budget`、`max_market_usdc - current_exposure`、`max_order_usdc`、`available_usdc`、orderbook ask 侧可成交深度的最小值。
- 处理 `min_order_size`、深度不足、风控限制导致的买不满，将未用资金释放并重新分配给其他 eligible markets。
- 在新 target market、价格更新、成交更新、FAK no fill、FAK partial fill、订单取消、持仓校准时支持重算。

## 交付物

- `AllocationPlan`、`MarketBuyBudgetChanged`、释放资金原因字段。
- 可解释的跳过原因，例如无 eligible market、低于 min order size、已达单 market 上限、流动性不足、总预算不足。
- 不直接下单；只向 Strategy Engine 提供计划。

## 并行接口

- 依赖 `Market Registry`、`OrderbookSnapshot`、`Position` 和风控配置字段。
- 输出供 `01-strategy-domain/04-strategy-engine-state-machine` 与 `02-trading-execution-risk/01-risk-manager` 使用。
- 与 `04-infra-persistence/05-config-secrets` 对齐配置名：`portfolio_budget_usdc`、`max_order_usdc`、`max_market_usdc`、`max_total_usdc`、`min_liquidity_usdc`、`max_spread`。

## 注释要求

对等权目标、资金释放、open SELL 计入 exposure 和 FAK pending BUY 近似为 0 的原因写中文注释。开发阶段不运行测试。

