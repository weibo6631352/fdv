from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.allocation import Allocation, AllocationMarketSnapshot, AllocationPlan
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import OrderSide
from fdv_trader.strategy_api.config_loader import load_strategy_config
from fdv_trader.strategy_api.models import (
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)
from fdv_trader.strategies.template.config import TemplateStrategyConfig


class TemplateStrategy:
    def __init__(self, config: TemplateStrategyConfig | None = None) -> None:
        self._config = config or TemplateStrategyConfig()
        self._spec = StrategySpec(
            name="template",
            version="1",
            description="Example strategy scaffold for secondary development",
            config_type=TemplateStrategyConfig,
            capabilities=("universe", "sizing", "entry", "exit", "recovery"),
        )

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def select_market(self, market: Market) -> UniverseDecision:
        if self._config.required_category and market.category != self._config.required_category:
            return UniverseDecision.exclude(reason="category_mismatch")
        required_keywords = {keyword.lower() for keyword in self._config.required_keywords}
        market_keywords = {keyword.lower() for keyword in market.matched_keywords}
        if required_keywords and not required_keywords.issubset(market_keywords):
            return UniverseDecision.exclude(reason="keyword_mismatch")
        return UniverseDecision.include(reason="template_market_selected")

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

        available_usdc = _metadata_decimal(context, "available_usdc") or portfolio_budget_usdc
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
            entry_no_price_max=_metadata_decimal(context, "entry_no_price_max")
            or self._config.entry_price_max,
            min_liquidity_usdc=_metadata_decimal(context, "min_liquidity_usdc") or Decimal("0"),
            max_spread=_metadata_decimal(context, "max_spread"),
        )
        allocation = _pick_allocation(
            plan.allocations,
            context.market.condition_id if context.market is not None else None,
        )
        return EntrySizing(
            allocation_plan=plan,
            allocation=allocation,
            reason=(allocation.reason if allocation is not None and allocation.reason else plan.reason),
        )

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        if context.market is None or context.orderbook is None:
            return StrategyDecision.skip(reason="missing_market_state")
        best_ask = context.orderbook.best_ask
        if best_ask is None or best_ask > self._config.entry_price_max:
            return StrategyDecision.skip(reason="entry_price_rejected")
        amount_usdc = _metadata_decimal(context, "amount_usdc", "buy_budget_usdc")
        if amount_usdc is None or amount_usdc <= Decimal("0"):
            return StrategyDecision.skip(reason="missing_entry_amount")
        return StrategyDecision.buy(
            reason="template_entry",
            price=self._config.entry_price_max,
            amount_usdc=amount_usdc,
            market_slug=context.market.market_slug,
        )

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        size_shares = _metadata_decimal(context, "size_shares")
        if size_shares is None and context.position is not None:
            size_shares = context.position.shares - context.position.open_sell_shares
        if size_shares is None or size_shares <= Decimal("0"):
            return StrategyDecision.skip(reason="missing_exit_size")
        return StrategyDecision.sell(
            reason="template_exit",
            price=self._config.exit_price,
            size_shares=size_shares,
            market_slug=(
                context.market.market_slug
                if context.market is not None
                else _metadata_text(context, "market_slug")
            ),
        )

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        if context.market is None:
            return RecoveryDecision(reason="missing_market_state")
        position = context.position
        if position is None and context.account_snapshot is not None:
            position = context.account_snapshot.get_position(
                context.market.condition_id,
                context.market.no_token_id,
            )
        open_orders = context.open_orders
        if not open_orders and context.account_snapshot is not None:
            open_orders = context.account_snapshot.open_orders_for_market(
                context.market.condition_id,
                context.market.no_token_id,
            )
        cancel_order_ids = tuple(
            order_id
            for order in open_orders
            for order_id in (_order_identifier(order),)
            if order_id is not None and order.side == OrderSide.BUY and order.open
        )
        pause_market = context.market.trading_status in {
            TradingStatus.PAUSED,
            TradingStatus.CLOSED,
            TradingStatus.RESOLVED,
        }
        return RecoveryDecision(
            reason="template_recovery",
            target_sell_size_shares=position.shares if position is not None else Decimal("0"),
            cancel_order_ids=cancel_order_ids,
            pause_market=pause_market,
            pause_reason="market_not_tradable" if pause_market else "",
        )


def build_strategy(config_path: str | None = None) -> TemplateStrategy:
    config = load_strategy_config(TemplateStrategyConfig, config_path)
    return TemplateStrategy(config=config)


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
    return ()


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
