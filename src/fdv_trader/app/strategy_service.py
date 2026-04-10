from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from fdv_trader.domain.allocation import Allocation, AllocationMarketSnapshot, AllocationPlan
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import (
    BuyOrderIntent,
    CancelOrderIntent,
    Order,
    ReplaceOrderIntent,
    SellOrderIntent,
)
from fdv_trader.domain.orderbook import OrderbookSnapshot
from fdv_trader.domain.position import Position
from fdv_trader.domain.strategy import StrategyEngine
from fdv_trader.observability.trace import ensure_trace_id
from fdv_trader.runtime.account_state import AccountSnapshot
from fdv_trader.runtime.registry import MarketRegistry

OrderbookReader = Callable[[str], OrderbookSnapshot | None]


class StrategyService:
    """Builds allocation and buy intent candidates from hot runtime snapshots."""

    def __init__(
        self,
        *,
        strategy_engine: StrategyEngine | None = None,
        registry: MarketRegistry | None = None,
        orderbook_reader: OrderbookReader | None = None,
    ) -> None:
        self._strategy_engine = strategy_engine or StrategyEngine()
        self._registry = registry
        self._orderbook_reader = orderbook_reader

    def build_entry_plan(
        self,
        *,
        market: Market | None = None,
        orderbook: OrderbookSnapshot | None = None,
        account_snapshot: AccountSnapshot | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        trace_id: str | None = None,
        portfolio_budget_usdc: Decimal,
        available_usdc: Decimal | None = None,
        max_order_usdc: Decimal,
        max_market_usdc: Decimal,
        max_total_usdc: Decimal,
        positions: Iterable[Position] = (),
        open_orders: Iterable[Order] = (),
        entry_no_price_max: Decimal = Decimal("0.60"),
        min_liquidity_usdc: Decimal = Decimal("0"),
        max_spread: Decimal | None = None,
    ) -> "StrategyEntryPlan":
        trace_id = trace_id or ensure_trace_id()
        if account_snapshot is not None:
            if available_usdc is None:
                available_usdc = account_snapshot.balance_usdc
            if not positions:
                positions = account_snapshot.positions
            if not open_orders:
                open_orders = account_snapshot.open_orders
        resolved_market = market or self._resolve_market(condition_id=condition_id, token_id=token_id)
        resolved_orderbook = orderbook or self._resolve_orderbook(
            market=resolved_market,
            token_id=token_id,
        )
        if resolved_market is None or resolved_orderbook is None:
            return StrategyEntryPlan(
                trace_id=trace_id,
                market=resolved_market,
                orderbook=resolved_orderbook,
                allocation_plan=AllocationPlan(
                    trace_id=trace_id,
                    total_budget_usdc=portfolio_budget_usdc,
                    reason="missing_market_state",
                ),
                allocation=None,
                intent=None,
                eligible_market_count=0,
                reason="missing_market_state",
            )

        if account_snapshot is not None and resolved_market is not None:
            if not account_snapshot.allow_new_buys or account_snapshot.is_market_paused(
                resolved_market.condition_id
            ):
                return StrategyEntryPlan(
                    trace_id=trace_id,
                    market=resolved_market,
                    orderbook=resolved_orderbook,
                    allocation_plan=AllocationPlan(
                        trace_id=trace_id,
                        total_budget_usdc=portfolio_budget_usdc,
                        reason="buying_paused",
                    ),
                    allocation=None,
                    intent=None,
                    eligible_market_count=0,
                    reason="buying_paused",
                )

        positions = tuple(positions)
        open_orders = tuple(open_orders)
        position_index = {
            (position.condition_id, position.token_id): position for position in positions
        }
        candidate_snapshots = self._build_market_snapshots(
            trace_id=trace_id,
            focus_market=resolved_market,
            focus_orderbook=resolved_orderbook,
            position_index=position_index,
            open_orders=open_orders,
            entry_no_price_max=entry_no_price_max,
        )
        if not candidate_snapshots:
            candidate_snapshots = (
                self._build_market_snapshot(
                    trace_id=trace_id,
                    market=resolved_market,
                    orderbook=resolved_orderbook,
                    position=position_index.get((resolved_market.condition_id, resolved_market.no_token_id)),
                    open_orders=open_orders,
                    entry_no_price_max=entry_no_price_max,
                ),
            )

        plan = AllocationPlan.equal_weight(
            trace_id=trace_id,
            portfolio_budget_usdc=portfolio_budget_usdc,
            markets=candidate_snapshots,
            available_usdc=available_usdc if available_usdc is not None else portfolio_budget_usdc,
            max_order_usdc=max_order_usdc,
            max_market_usdc=max_market_usdc,
            max_total_usdc=max_total_usdc,
            entry_no_price_max=entry_no_price_max,
            min_liquidity_usdc=min_liquidity_usdc,
            max_spread=max_spread,
        )
        allocation = _pick_allocation(plan.allocations, resolved_market.condition_id)
        intent = None
        reason = plan.reason
        if allocation is not None:
            reason = allocation.reason or reason
            if allocation.buy_budget_usdc > Decimal("0"):
                intent = self._strategy_engine.build_buy_intent(
                    trace_id=trace_id,
                    condition_id=resolved_market.condition_id,
                    no_token_id=resolved_market.no_token_id,
                    amount_usdc=allocation.buy_budget_usdc,
                    market_slug=resolved_market.market_slug,
                )
        return StrategyEntryPlan(
            trace_id=trace_id,
            market=resolved_market,
            orderbook=resolved_orderbook,
            allocation_plan=plan,
            allocation=allocation,
            intent=intent,
            eligible_market_count=plan.eligible_market_count,
            reason=reason,
        )

    def build_sell_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        size_shares: Decimal,
        market_slug: str | None = None,
    ) -> SellOrderIntent:
        return self._strategy_engine.build_sell_intent(
            trace_id=trace_id,
            condition_id=condition_id,
            no_token_id=no_token_id,
            size_shares=size_shares,
            market_slug=market_slug,
        )

    def build_cancel_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        order_id: str,
        market_slug: str | None = None,
        reason: str = "",
    ) -> CancelOrderIntent:
        return self._strategy_engine.build_cancel_intent(
            trace_id=trace_id,
            condition_id=condition_id,
            no_token_id=no_token_id,
            order_id=order_id,
            market_slug=market_slug,
            reason=reason,
        )

    def build_replace_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        order_id: str,
        size_shares: Decimal,
        market_slug: str | None = None,
        reason: str = "",
    ) -> ReplaceOrderIntent:
        return self._strategy_engine.build_replace_intent(
            trace_id=trace_id,
            condition_id=condition_id,
            no_token_id=no_token_id,
            order_id=order_id,
            size_shares=size_shares,
            market_slug=market_slug,
            reason=reason,
        )

    def _build_market_snapshots(
        self,
        *,
        trace_id: str,
        focus_market: Market,
        focus_orderbook: OrderbookSnapshot,
        position_index: dict[tuple[str, str], Position],
        open_orders: tuple[Order, ...],
        entry_no_price_max: Decimal,
    ) -> tuple[AllocationMarketSnapshot, ...]:
        markets = (
            self._registry.snapshot().markets
            if self._registry is not None and self._registry.snapshot().markets
            else (focus_market,)
        )
        snapshots: list[AllocationMarketSnapshot] = []
        for candidate in markets:
            candidate_orderbook = (
                focus_orderbook
                if candidate.condition_id == focus_market.condition_id
                else self._lookup_orderbook(candidate.no_token_id)
            )
            if candidate_orderbook is None:
                continue
            position = position_index.get((candidate.condition_id, candidate.no_token_id))
            candidate_open_orders = tuple(
                order
                for order in open_orders
                if order.condition_id == candidate.condition_id and order.token_id == candidate.no_token_id
            )
            snapshots.append(
                self._build_market_snapshot(
                    trace_id=trace_id,
                    market=candidate,
                    orderbook=candidate_orderbook,
                    position=position,
                    open_orders=candidate_open_orders,
                    entry_no_price_max=entry_no_price_max,
                )
            )
        return tuple(snapshots)

    def _build_market_snapshot(
        self,
        *,
        trace_id: str,
        market: Market,
        orderbook: OrderbookSnapshot,
        position: Position | None,
        open_orders: tuple[Order, ...],
        entry_no_price_max: Decimal,
    ) -> AllocationMarketSnapshot:
        classification_passed = _market_has_target_classification(market)
        return AllocationMarketSnapshot(
            market=market,
            orderbook=orderbook,
            position=position,
            open_orders=open_orders,
            classification_passed=classification_passed,
            classification_reason=None if classification_passed else "not_crypto_fdv_500m",
            tradable=market.trading_status == TradingStatus.ELIGIBLE,
            risk_allowed=True,
            market_active=market.trading_status == TradingStatus.ELIGIBLE,
            market_open=market.trading_status == TradingStatus.ELIGIBLE,
            clob_enabled=True,
            resolved=market.trading_status == TradingStatus.RESOLVED,
            cancelled=False,
            archived=market.trading_status == TradingStatus.CLOSED,
            liquidity_usdc=_ask_depth_notional(orderbook, entry_no_price_max),
            spread=orderbook.spread,
            best_ask=orderbook.best_ask,
            best_ask_size=orderbook.best_ask_size,
            idempotency_key=f"{trace_id}:{market.condition_id}:{market.no_token_id}",
        )

    def _resolve_market(
        self,
        *,
        condition_id: str | None,
        token_id: str | None,
    ) -> Market | None:
        if self._registry is None:
            return None
        if condition_id is not None:
            market = self._registry.get_by_condition_id(condition_id)
            if market is not None:
                return market
        if token_id is not None:
            return self._registry.get_by_no_token_id(token_id)
        return None

    def _resolve_orderbook(
        self,
        *,
        market: Market | None,
        token_id: str | None,
    ) -> OrderbookSnapshot | None:
        lookup_token_id = token_id or (market.no_token_id if market is not None else None)
        if lookup_token_id is None:
            return None
        return self._lookup_orderbook(lookup_token_id)

    def _lookup_orderbook(self, token_id: str) -> OrderbookSnapshot | None:
        if self._orderbook_reader is None:
            return None
        return self._orderbook_reader(token_id)


@dataclass(frozen=True, slots=True)
class StrategyEntryPlan:
    trace_id: str
    market: Market | None
    orderbook: OrderbookSnapshot | None
    allocation_plan: AllocationPlan
    allocation: Allocation | None
    intent: BuyOrderIntent | None
    eligible_market_count: int = 0
    reason: str = ""

    @property
    def ready_to_trade(self) -> bool:
        return self.intent is not None and self.allocation is not None and self.market is not None


def _pick_allocation(
    allocations: tuple[Allocation, ...],
    condition_id: str,
) -> Allocation | None:
    for allocation in allocations:
        if allocation.condition_id == condition_id:
            return allocation
    return None


def _ask_depth_notional(orderbook: OrderbookSnapshot, price_cap: Decimal) -> Decimal:
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


def _market_has_target_classification(market: Market) -> bool:
    matched_keywords = {keyword.strip().lower() for keyword in market.matched_keywords}
    category_tokens = {str(market.category or "").strip().lower()}
    category_tokens.update(tag.strip().lower() for tag in market.tags)
    has_crypto = "crypto" in category_tokens or "cryptocurrency" in category_tokens
    return has_crypto and "fdv" in matched_keywords and "500m" in matched_keywords
