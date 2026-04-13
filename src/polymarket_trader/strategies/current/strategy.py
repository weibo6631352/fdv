from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.allocation import Allocation, AllocationMarketSnapshot, AllocationPlan
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import OrderSide
from polymarket_trader.strategy_api.config_loader import load_strategy_config
from polymarket_trader.strategy_api.models import (
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)
from polymarket_trader.strategies.current.config import CurrentStrategyConfig


class CurrentStrategy:
    """Single runtime strategy implementation and customization base."""

    def __init__(self, config: CurrentStrategyConfig | None = None) -> None:
        self._config = config or CurrentStrategyConfig()
        self._spec = StrategySpec(
            name="current",
            version="1",
            description="Current runtime strategy implementation",
            config_type=CurrentStrategyConfig,
            capabilities=("universe", "sizing", "entry", "exit", "recovery"),
        )

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def select_market(self, market: Market) -> UniverseDecision:
        return _select_market(market)

    def size_entry(self, context: StrategyContext) -> EntrySizing:
        portfolio_budget_usdc = _metadata_decimal(context, "portfolio_budget_usdc")
        if portfolio_budget_usdc is None:
            return _empty_sizing(context, reason="missing_portfolio_budget")

        candidate_snapshots = _candidate_snapshots(context)
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

        min_liquidity_usdc = _metadata_decimal(context, "min_liquidity_usdc")
        if min_liquidity_usdc is None:
            min_liquidity_usdc = Decimal("0")

        plan = AllocationPlan.equal_weight(
            trace_id=context.trace_id,
            portfolio_budget_usdc=portfolio_budget_usdc,
            markets=candidate_snapshots,
            available_usdc=available_usdc,
            max_order_usdc=max_order_usdc,
            max_market_usdc=max_market_usdc,
            max_total_usdc=max_total_usdc,
            entry_no_price_max=_metadata_decimal(context, "entry_no_price_max")
            or self._config.entry_no_price_max,
            min_liquidity_usdc=min_liquidity_usdc,
            max_spread=_metadata_decimal(context, "max_spread"),
        )
        allocation = _pick_allocation(
            plan.allocations,
            context.market.condition_id if context.market is not None else None,
        )
        reason = _sizing_reason(plan, allocation)
        return EntrySizing(
            allocation_plan=plan,
            allocation=allocation,
            reason=reason,
        )

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        if context.market is None or context.orderbook is None:
            return StrategyDecision.skip(reason="missing_market_state")
        best_ask = context.orderbook.best_ask
        if best_ask is None:
            return StrategyDecision.skip(reason="missing_best_ask")
        if best_ask > self._config.entry_no_price_max:
            return StrategyDecision.skip(reason="price_above_entry_max")

        amount_usdc = _metadata_decimal(context, "amount_usdc", "buy_budget_usdc")
        if amount_usdc is None or amount_usdc <= Decimal("0"):
            return StrategyDecision.skip(reason="missing_entry_amount")

        return StrategyDecision.buy(
            reason="strategy_entry",
            price=self._config.entry_no_price_max,
            amount_usdc=amount_usdc,
            market_slug=context.market.market_slug,
        )

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
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
            price=self._config.exit_no_price,
            size_shares=uncovered_shares,
            market_slug=(
                context.market.market_slug
                if context.market is not None
                else _metadata_text(context, "market_slug")
            ),
        )

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        if context.market is None:
            return RecoveryDecision(reason="missing_market_state")

        account_snapshot = context.account_snapshot
        position = context.position
        if position is None and account_snapshot is not None:
            position = account_snapshot.get_position(
                context.market.condition_id,
                context.market.no_token_id,
            )

        open_orders = context.open_orders
        if not open_orders and account_snapshot is not None:
            open_orders = account_snapshot.open_orders_for_market(
                context.market.condition_id,
                context.market.no_token_id,
            )

        cancel_order_ids = tuple(
            order_id
            for order in open_orders
            for order_id in (_order_identifier(order),)
            if order_id is not None and _is_open_buy(order)
        )
        pause_market = context.market.trading_status in {
            TradingStatus.PAUSED,
            TradingStatus.CLOSED,
            TradingStatus.RESOLVED,
        } or (
            account_snapshot is not None
            and account_snapshot.is_market_paused(context.market.condition_id)
        )
        pause_reason = "market_not_tradable" if pause_market else ""

        return RecoveryDecision(
            reason="strategy_recovery",
            target_sell_size_shares=position.shares if position is not None else Decimal("0"),
            cancel_order_ids=cancel_order_ids,
            pause_market=pause_market,
            pause_reason=pause_reason,
        )


def build_strategy(config_path: str | None = None) -> CurrentStrategy:
    config = load_strategy_config(CurrentStrategyConfig, config_path)
    return CurrentStrategy(config=config)


def _empty_sizing(context: StrategyContext, *, reason: str) -> EntrySizing:
    total_budget_usdc = _metadata_decimal(context, "portfolio_budget_usdc") or Decimal("0")
    return EntrySizing(
        allocation_plan=AllocationPlan(
            trace_id=context.trace_id,
            total_budget_usdc=total_budget_usdc,
            reason=reason,
        ),
        reason=reason,
    )


def _candidate_snapshots(context: StrategyContext) -> tuple[AllocationMarketSnapshot, ...]:
    raw_value = context.metadata.get("candidate_snapshots")
    if isinstance(raw_value, tuple):
        return tuple(
            snapshot for snapshot in raw_value if isinstance(snapshot, AllocationMarketSnapshot)
        )
    if isinstance(raw_value, list):
        return tuple(
            snapshot for snapshot in raw_value if isinstance(snapshot, AllocationMarketSnapshot)
        )
    fallback = _fallback_snapshot(context)
    return () if fallback is None else (fallback,)


def _fallback_snapshot(context: StrategyContext) -> AllocationMarketSnapshot | None:
    if context.market is None or context.orderbook is None:
        return None
    universe_decision = _select_market(context.market)
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
        liquidity_usdc=_ask_depth_notional(
            context.orderbook,
            price_cap=context.orderbook.best_ask or Decimal("0"),
        ),
        spread=context.orderbook.spread,
        best_ask=context.orderbook.best_ask,
        best_ask_size=context.orderbook.best_ask_size,
        idempotency_key=f"{context.trace_id}:{context.market.condition_id}:{context.market.no_token_id}",
    )


def _ask_depth_notional(orderbook, *, price_cap: Decimal) -> Decimal:
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


def _select_market(market: Market) -> UniverseDecision:
    category_tokens = _normalized_tokens(" ".join(_non_empty(market.category, *market.tags)))
    event_tokens = _normalized_tokens(market.event_title)
    market_tokens = _normalized_tokens(" ".join(_non_empty(market.market_question, market.market_name, market.market_slug)))

    has_category = bool({"crypto", "cryptocurrency"} & category_tokens)
    has_fdv = "fdv" in event_tokens or (
        {"fully", "diluted", "valuation"} <= event_tokens
    )
    has_500m = "500m" in market_tokens
    if has_category and has_fdv and has_500m:
        return UniverseDecision.include(reason="selected_by_strategy")
    return UniverseDecision.exclude(reason="market_out_of_universe")


def _pick_allocation(
    allocations: tuple[Allocation, ...],
    condition_id: str | None,
) -> Allocation | None:
    if condition_id is None:
        return None
    for allocation in allocations:
        if allocation.condition_id == condition_id:
            return allocation
    return None


def _sizing_reason(plan: AllocationPlan, allocation: Allocation | None) -> str:
    if allocation is not None and allocation.reason:
        return allocation.reason
    return plan.reason


def _metadata_decimal(context: StrategyContext, *keys: str) -> Decimal | None:
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
    for key in keys:
        value = context.metadata.get(key)
        if value is not None:
            return str(value)
    return None


def _order_identifier(order) -> str | None:
    return order.order_id or order.idempotency_key


def _is_open_buy(order) -> bool:
    return order.side == OrderSide.BUY and order.open


def _non_empty(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _normalized_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    normalized = (
        text.lower()
        .replace("$500 million", "500m")
        .replace("500 million", "500m")
        .replace("500,000,000", "500m")
        .replace("$500m", "500m")
        .replace("500 m", "500m")
        .replace("fully diluted valuation", "fdv")
    )
    parts: list[str] = []
    current: list[str] = []
    for char in normalized:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return {part for part in parts if part}
