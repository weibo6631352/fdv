"""当前策略的资金分配、入场和退出决策。

这个文件关注的是“拿到市场和账户上下文后，策略怎么做交易决定”，
不负责远端扫描，也不负责恢复修复语义。
"""

from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.allocation import Allocation, AllocationMarketSnapshot, AllocationPlan
from polymarket_trader.domain.market import TradingStatus
from strategy_sdk import EntrySizing, StrategyContext, StrategyDecision, StrategyRuntimeProfile

from strategies.current.config import CurrentStrategyConfig
from strategies.current.universe import select_market


def size_entry(config: CurrentStrategyConfig, context: StrategyContext) -> EntrySizing:
    """为当前 market 计算本轮可用入场预算。

    参数：
        config:
            当前策略配置，主要提供价格、深度、spread 等门槛。
        context:
            框架传入的策略上下文。这里依赖其中的市场快照、候选市场列表、
            组合预算和各种上限信息。

    返回：
        ``EntrySizing``，包含：
        - 整体 ``AllocationPlan``
        - 当前目标 market 的 ``Allocation``（如果有）
        - 一个易读的原因字符串

    说明：
        当前默认策略采用“等权分配”。
        也就是说，先找出所有可参与分配的候选市场，再在这些市场之间平均分配预算。
    """

    portfolio_budget_usdc = _metadata_decimal(context, "portfolio_budget_usdc")
    if portfolio_budget_usdc is None:
        return _empty_sizing(context, reason="missing_portfolio_budget")

    candidate_snapshots = _candidate_snapshots(config, context)
    if not candidate_snapshots:
        return EntrySizing(
            allocation_plan=AllocationPlan(
                trace_id=context.trace_id,
                total_budget_usdc=portfolio_budget_usdc,
                reason="missing_market_state",
            ),
            reason="missing_market_state",
        )

    available_usdc = _metadata_decimal(context, "available_usdc")
    if available_usdc is None:
        available_usdc = portfolio_budget_usdc

    max_order_usdc = _metadata_decimal(context, "max_order_usdc")
    if max_order_usdc is None:
        return _empty_sizing(context, reason="missing_max_order_usdc")

    max_market_usdc = _metadata_decimal(context, "max_market_usdc")
    if max_market_usdc is None:
        return _empty_sizing(context, reason="missing_max_market_usdc")

    max_total_usdc = _metadata_decimal(context, "max_total_usdc")
    if max_total_usdc is None:
        return _empty_sizing(context, reason="missing_max_total_usdc")

    plan = AllocationPlan.equal_weight(
        trace_id=context.trace_id,
        portfolio_budget_usdc=portfolio_budget_usdc,
        markets=candidate_snapshots,
        available_usdc=available_usdc,
        max_order_usdc=max_order_usdc,
        max_market_usdc=max_market_usdc,
        max_total_usdc=max_total_usdc,
        runtime_profile=StrategyRuntimeProfile(
            entry_no_price_max=config.entry_no_price_max,
            min_liquidity_usdc=config.min_liquidity_usdc,
            max_spread=config.max_spread,
        ),
    )
    allocation = _pick_allocation(
        plan.allocations,
        context.market.condition_id if context.market is not None else None,
    )
    return EntrySizing(
        allocation_plan=plan,
        allocation=allocation,
        reason=_sizing_reason(plan, allocation),
    )


def decide_entry(config: CurrentStrategyConfig, context: StrategyContext) -> StrategyDecision:
    """根据盘口和预算生成 BUY 决策。

    参数：
        config:
            当前策略配置，主要使用 ``entry_no_price_max``。
        context:
            当前 market 的策略上下文。要求其中至少有 ``market``、
            ``orderbook``，以及 metadata 中的 ``amount_usdc`` 或
            ``buy_budget_usdc``。

    返回：
        一个 ``StrategyDecision``：
        - 条件满足时返回 ``BUY``；
        - 条件不足时返回 ``SKIP`` 并说明原因。
    """

    if context.market is None or context.orderbook is None:
        return StrategyDecision.skip(reason="missing_market_state")
    best_ask = context.orderbook.best_ask
    if best_ask is None:
        return StrategyDecision.skip(reason="missing_best_ask")
    if best_ask > config.entry_no_price_max:
        return StrategyDecision.skip(reason="price_above_entry_max")

    amount_usdc = _metadata_decimal(context, "amount_usdc", "buy_budget_usdc")
    if amount_usdc is None or amount_usdc <= Decimal("0"):
        return StrategyDecision.skip(reason="missing_entry_amount")

    return StrategyDecision.buy(
        reason="strategy_entry",
        price=config.entry_no_price_max,
        amount_usdc=amount_usdc,
        market_slug=context.market.market_slug,
    )


def decide_exit(config: CurrentStrategyConfig, context: StrategyContext) -> StrategyDecision:
    """根据持仓状态生成 SELL 决策。

    参数：
        config:
            当前策略配置，主要使用 ``exit_no_price``。
        context:
            当前持仓的策略上下文。可以显式在 metadata 中传
            ``size_shares``，也可以依赖 ``position`` 自动推导未覆盖仓位。

    返回：
        一个 ``StrategyDecision``：
        - 有可卖份额时返回 ``SELL``；
        - 否则返回 ``SKIP``。
    """

    size_shares = _metadata_decimal(context, "size_shares")
    if size_shares is not None and size_shares > Decimal("0"):
        uncovered_shares = size_shares
    elif context.position is not None:
        uncovered_shares = context.position.shares - context.position.open_sell_shares
    else:
        return StrategyDecision.skip(reason="missing_position_state")
    if uncovered_shares <= Decimal("0"):
        return StrategyDecision.skip(reason="no_uncovered_shares")

    return StrategyDecision.sell(
        reason="strategy_exit",
        price=config.exit_no_price,
        size_shares=uncovered_shares,
        market_slug=(
            context.market.market_slug if context.market is not None else _metadata_text(context, "market_slug")
        ),
    )


def _empty_sizing(context: StrategyContext, *, reason: str) -> EntrySizing:
    """构造一个“无可分配预算”的占位结果。

    参数：
        context:
            当前策略上下文。
        reason:
            当前无法完成分配的原因。

    返回：
        一个不包含 allocation 的 ``EntrySizing``。
    """

    total_budget_usdc = _metadata_decimal(context, "portfolio_budget_usdc") or Decimal("0")
    return EntrySizing(
        allocation_plan=AllocationPlan(
            trace_id=context.trace_id,
            total_budget_usdc=total_budget_usdc,
            reason=reason,
        ),
        reason=reason,
    )


def _candidate_snapshots(
    config: CurrentStrategyConfig,
    context: StrategyContext,
) -> tuple[AllocationMarketSnapshot, ...]:
    """从上下文中提取候选市场快照。

    参数：
        config:
            当前策略配置。只有在缺少候选列表时，才会用于构造 fallback snapshot。
        context:
            策略上下文，优先从 ``metadata['candidate_snapshots']`` 里取候选市场。

    返回：
        一组 ``AllocationMarketSnapshot``。

    说明：
        正常路径下，框架会把候选市场列表放在 metadata 里。
        如果当前调用点没有提供这个列表，这里会退化为只用当前 market
        生成一个 fallback snapshot，保证逻辑仍可运行。
    """

    raw_value = context.metadata.get("candidate_snapshots")
    if isinstance(raw_value, tuple):
        return tuple(snapshot for snapshot in raw_value if isinstance(snapshot, AllocationMarketSnapshot))
    if isinstance(raw_value, list):
        return tuple(snapshot for snapshot in raw_value if isinstance(snapshot, AllocationMarketSnapshot))
    fallback = _fallback_snapshot(config, context)
    return () if fallback is None else (fallback,)


def _fallback_snapshot(
    config: CurrentStrategyConfig,
    context: StrategyContext,
) -> AllocationMarketSnapshot | None:
    """在缺少候选市场列表时，为当前 market 构造一个最小快照。

    参数：
        config:
            当前策略配置。
        context:
            当前策略上下文，要求至少包含 market 和 orderbook。

    返回：
        一个可参与分配计算的 ``AllocationMarketSnapshot``；
        如果上下文信息不足，则返回 ``None``。
    """

    if context.market is None or context.orderbook is None:
        return None
    universe_decision = select_market(config, context.market)
    return AllocationMarketSnapshot(
        market=context.market,
        orderbook=context.orderbook,
        position=context.position,
        open_orders=context.open_orders,
        classification_passed=universe_decision.selected,
        classification_reason=None if universe_decision.selected else universe_decision.reason,
        tradable=context.market.trading_status == TradingStatus.ELIGIBLE,
        risk_allowed=True,
        market_active=context.market.trading_status == TradingStatus.ELIGIBLE,
        market_open=context.market.trading_status == TradingStatus.ELIGIBLE,
        clob_enabled=True,
        resolved=context.market.trading_status == TradingStatus.RESOLVED,
        cancelled=False,
        archived=context.market.trading_status == TradingStatus.CLOSED,
        liquidity_usdc=_ask_depth_notional(context.orderbook, price_cap=config.entry_no_price_max),
        spread=context.orderbook.spread,
        best_ask=context.orderbook.best_ask,
        best_ask_size=context.orderbook.best_ask_size,
        idempotency_key=f"{context.trace_id}:{context.market.condition_id}:{context.market.no_token_id}",
    )


def _ask_depth_notional(orderbook, *, price_cap: Decimal) -> Decimal:
    """计算价格上限内的 ask 侧深度总额。

    参数：
        orderbook:
            当前盘口快照。
        price_cap:
            允许吃单的最高价格。高于这个价格的 ask 不计入深度。

    返回：
        在价格上限内可立即成交的深度总额，单位 USDC。
    """

    depth_usdc = Decimal("0")
    levels = orderbook.asks
    if not levels and orderbook.best_ask is not None and orderbook.best_ask_size is not None:
        if orderbook.best_ask <= price_cap:
            return orderbook.best_ask * orderbook.best_ask_size
        return Decimal("0")
    for level in levels:
        if level.price <= price_cap:
            depth_usdc += level.price * level.size
    return depth_usdc


def _pick_allocation(
    allocations: tuple[Allocation, ...],
    condition_id: str | None,
) -> Allocation | None:
    """从分配结果中挑出当前目标 market 的那一项。"""

    if condition_id is None:
        return None
    for allocation in allocations:
        if allocation.condition_id == condition_id:
            return allocation
    return None


def _sizing_reason(plan: AllocationPlan, allocation: Allocation | None) -> str:
    """返回对外展示时更有解释力的 sizing 原因。

    优先使用当前 allocation 的具体原因；
    如果当前 market 没有单独原因，再退回整体 plan 的原因。
    """

    if allocation is not None and allocation.reason:
        return allocation.reason
    return plan.reason


def _metadata_decimal(context: StrategyContext, *keys: str) -> Decimal | None:
    """按优先顺序从 metadata 中读取十进制数值。

    参数：
        context:
            当前策略上下文。
        *keys:
            允许尝试的 metadata key 列表。会按传入顺序依次尝试。

    返回：
        解析成功时返回 ``Decimal``，否则返回 ``None``。
    """

    for key in keys:
        value = context.metadata.get(key)
        if value is None:
            continue
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return None
    return None


def _metadata_text(context: StrategyContext, *keys: str) -> str | None:
    """按优先顺序从 metadata 中读取文本值。"""

    for key in keys:
        value = context.metadata.get(key)
        if value is not None:
            return str(value)
    return None
