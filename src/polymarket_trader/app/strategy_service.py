from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from polymarket_trader.domain.allocation import Allocation, AllocationPlan
from polymarket_trader.domain.market import Market
from polymarket_trader.domain.order import (
    BuyOrderIntent,
    CancelOrderIntent,
    ManagedOrderIntent,
    Order,
    OrderType,
    ReplaceOrderIntent,
    SellOrderIntent,
    TradableOrderIntent,
)
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.domain.position import Position
from polymarket_trader.observability.trace import ensure_trace_id
from polymarket_trader.runtime.account_state import AccountSnapshot
from polymarket_trader.runtime.registry import MarketRegistry
from strategy_sdk import (
    EntryCandidate,
    MarketTokenView,
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyModule,
)

OrderbookReader = Callable[[str], OrderbookSnapshot | None]


class StrategyService:
    """Builds allocation plans and bridges strategy decisions into order intents."""

    def __init__(
        self,
        *,
        strategy_module: StrategyModule,
        registry: MarketRegistry | None = None,
        orderbook_reader: OrderbookReader | None = None,
    ) -> None:
        self._strategy_module = strategy_module
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
        resolved_token_id = token_id or (orderbook.token_id if orderbook is not None else None)
        resolved_orderbook = orderbook or self._resolve_orderbook(
            market=resolved_market,
            token_id=resolved_token_id,
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

        if account_snapshot is not None:
            if not account_snapshot.allow_new_entries or account_snapshot.is_market_paused(
                resolved_market.condition_id
            ):
                return StrategyEntryPlan(
                    trace_id=trace_id,
                    market=resolved_market,
                    orderbook=resolved_orderbook,
                    allocation_plan=AllocationPlan(
                        trace_id=trace_id,
                        total_budget_usdc=portfolio_budget_usdc,
                        reason="entry_paused",
                    ),
                    allocation=None,
                    intent=None,
                    eligible_market_count=0,
                    reason="entry_paused",
                )

        positions = tuple(positions)
        open_orders = tuple(open_orders)
        position_index = {
            (position.condition_id, position.token_id): position for position in positions
        }
        entry_candidates = self._build_entry_candidates(
            trace_id=trace_id,
            focus_market=resolved_market,
            focus_token_id=resolved_token_id or resolved_orderbook.token_id,
            focus_orderbook=resolved_orderbook,
            position_index=position_index,
            open_orders=open_orders,
        )
        if not entry_candidates:
            entry_candidates = (
                self._build_entry_candidate(
                    trace_id=trace_id,
                    market=resolved_market,
                    token_id=resolved_token_id or resolved_orderbook.token_id,
                    orderbook=resolved_orderbook,
                    position=position_index.get(
                        (resolved_market.condition_id, resolved_token_id or resolved_orderbook.token_id)
                    ),
                    open_orders=tuple(
                        order
                        for order in open_orders
                        if order.condition_id == resolved_market.condition_id
                        and order.token_id == (resolved_token_id or resolved_orderbook.token_id)
                    ),
                ),
            )

        sizing = self._strategy_module.size_entry(
            StrategyContext(
                trace_id=trace_id,
                market=resolved_market,
                token_id=resolved_token_id,
                orderbook=resolved_orderbook,
                market_token_views=_market_token_views(
                    resolved_market,
                    orderbook_reader=self._orderbook_reader,
                    account_snapshot=account_snapshot,
                ),
                account_snapshot=account_snapshot,
                position=position_index.get((resolved_market.condition_id, resolved_token_id or "")),
                open_orders=tuple(
                    order
                    for order in open_orders
                    if order.condition_id == resolved_market.condition_id
                    and order.token_id == (resolved_token_id or "")
                ),
                entry_candidates=entry_candidates,
                now=resolved_orderbook.received_at,
                portfolio_budget_usdc=portfolio_budget_usdc,
                available_usdc=(
                    available_usdc if available_usdc is not None else portfolio_budget_usdc
                ),
                max_order_usdc=max_order_usdc,
                max_market_usdc=max_market_usdc,
                max_total_usdc=max_total_usdc,
                metadata={
                    "portfolio_budget_usdc": portfolio_budget_usdc,
                    "available_usdc": (
                        available_usdc if available_usdc is not None else portfolio_budget_usdc
                    ),
                    "max_order_usdc": max_order_usdc,
                    "max_market_usdc": max_market_usdc,
                    "max_total_usdc": max_total_usdc,
                },
            )
        )
        plan = sizing.allocation_plan
        allocation = sizing.allocation or _pick_allocation(
            plan.allocations,
            resolved_market.condition_id,
            resolved_token_id or resolved_orderbook.token_id,
        )
        reason = sizing.reason or plan.reason
        intent: TradableOrderIntent | None = None
        focus_token_id = allocation.token_id or resolved_token_id or resolved_orderbook.token_id
        focus_position = position_index.get((resolved_market.condition_id, focus_token_id))
        focus_open_orders = tuple(
            order
            for order in open_orders
            if order.condition_id == resolved_market.condition_id and order.token_id == focus_token_id
        )

        if allocation is not None:
            reason = allocation.reason or reason
            if allocation.buy_budget_usdc > Decimal("0"):
                decision = self._strategy_module.decide_entry(
                    StrategyContext(
                        trace_id=trace_id,
                        market=resolved_market,
                        token_id=allocation.token_id or resolved_token_id,
                        orderbook=resolved_orderbook,
                        market_token_views=_market_token_views(
                            resolved_market,
                            orderbook_reader=self._orderbook_reader,
                            account_snapshot=account_snapshot,
                        ),
                        account_snapshot=account_snapshot,
                        position=focus_position,
                        open_orders=focus_open_orders,
                        now=resolved_orderbook.received_at,
                        portfolio_budget_usdc=portfolio_budget_usdc,
                        available_usdc=available_usdc,
                        max_order_usdc=max_order_usdc,
                        max_market_usdc=max_market_usdc,
                        max_total_usdc=max_total_usdc,
                        allocation_plan=plan,
                        allocation=allocation,
                        amount_usdc=allocation.buy_budget_usdc,
                        metadata={
                            "allocation": allocation,
                            "allocation_plan": plan,
                            "amount_usdc": allocation.buy_budget_usdc,
                            "buy_budget_usdc": allocation.buy_budget_usdc,
                            "portfolio_budget_usdc": portfolio_budget_usdc,
                            "available_usdc": available_usdc,
                            "max_order_usdc": max_order_usdc,
                            "max_market_usdc": max_market_usdc,
                            "max_total_usdc": max_total_usdc,
                        },
                    )
                )
                intent = _decision_to_trade_intent(
                    trace_id=trace_id,
                    market=resolved_market,
                    default_token_id=focus_token_id,
                    decision=decision,
                )
                if intent is None and decision.reason:
                    reason = decision.reason

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

    def decide_follow_up(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        return self._strategy_module.decide_follow_up(context)

    def build_intent_from_decision(
        self,
        *,
        trace_id: str,
        condition_id: str,
        market_slug: str | None,
        default_token_id: str | None,
        decision: StrategyDecision,
    ) -> ManagedOrderIntent | None:
        return decision_to_managed_intent(
            trace_id=trace_id,
            condition_id=condition_id,
            market_slug=market_slug,
            default_token_id=default_token_id,
            decision=decision,
        )

    def _build_entry_candidates(
        self,
        *,
        trace_id: str,
        focus_market: Market,
        focus_token_id: str,
        focus_orderbook: OrderbookSnapshot,
        position_index: dict[tuple[str, str], Position],
        open_orders: tuple[Order, ...],
    ) -> tuple[EntryCandidate, ...]:
        markets = (
            self._registry.snapshot().markets
            if self._registry is not None and self._registry.snapshot().markets
            else (focus_market,)
        )
        candidates: list[EntryCandidate] = []
        for candidate in markets:
            for candidate_token_id in _candidate_token_ids(candidate):
                candidate_orderbook = (
                    focus_orderbook
                    if candidate.condition_id == focus_market.condition_id
                    and candidate_token_id == focus_token_id
                    else self._lookup_orderbook(candidate_token_id)
                )
                if candidate_orderbook is None:
                    continue
                position = position_index.get((candidate.condition_id, candidate_token_id))
                candidate_open_orders = tuple(
                    order
                    for order in open_orders
                    if order.condition_id == candidate.condition_id and order.token_id == candidate_token_id
                )
                candidates.append(
                    self._build_entry_candidate(
                        trace_id=trace_id,
                        market=candidate,
                        token_id=candidate_token_id,
                        orderbook=candidate_orderbook,
                        position=position,
                        open_orders=candidate_open_orders,
                    )
                )
        return tuple(candidates)

    def _build_entry_candidate(
        self,
        *,
        trace_id: str,
        market: Market,
        token_id: str,
        orderbook: OrderbookSnapshot,
        position: Position | None,
        open_orders: tuple[Order, ...],
    ) -> EntryCandidate:
        return EntryCandidate(
            market=market,
            token_id=token_id,
            orderbook=orderbook,
            position=position,
            open_orders=open_orders,
            idempotency_key=f"{trace_id}:{market.condition_id}:{token_id}",
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
            return self._registry.get_by_token_id(token_id)
        return None

    def _resolve_orderbook(
        self,
        *,
        market: Market | None,
        token_id: str | None,
    ) -> OrderbookSnapshot | None:
        if token_id is None:
            return None
        return self._lookup_orderbook(token_id)

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
    intent: TradableOrderIntent | None
    eligible_market_count: int = 0
    reason: str = ""

    @property
    def ready_to_trade(self) -> bool:
        return self.intent is not None and self.allocation is not None and self.market is not None


def _pick_allocation(
    allocations: tuple[Allocation, ...],
    condition_id: str,
    token_id: str,
) -> Allocation | None:
    for allocation in allocations:
        if allocation.condition_id == condition_id and allocation.token_id == token_id:
            return allocation
    return None


def _candidate_token_ids(market: Market) -> tuple[str, ...]:
    return market.token_ids


def _market_token_views(
    market: Market,
    *,
    orderbook_reader: OrderbookReader | None,
    account_snapshot: AccountSnapshot | None,
) -> tuple[MarketTokenView, ...]:
    return tuple(
        MarketTokenView(
            token_id=outcome.token_id,
            outcome=outcome.outcome,
            orderbook=(
                None
                if orderbook_reader is None
                else orderbook_reader(outcome.token_id)
            ),
            position=(
                None
                if account_snapshot is None
                else account_snapshot.get_position(market.condition_id, outcome.token_id)
            ),
            open_orders=(
                ()
                if account_snapshot is None
                else account_snapshot.open_orders_for_market(market.condition_id, outcome.token_id)
            ),
        )
        for outcome in market.outcomes
    )


def _decision_to_trade_intent(
    *,
    trace_id: str,
    market: Market,
    default_token_id: str | None,
    decision: StrategyDecision,
) -> TradableOrderIntent | None:
    intent = decision_to_managed_intent(
        trace_id=trace_id,
        condition_id=market.condition_id,
        market_slug=market.market_slug,
        default_token_id=default_token_id,
        decision=decision,
    )
    if isinstance(intent, (BuyOrderIntent, SellOrderIntent)):
        return intent
    return None


def decision_to_managed_intent(
    *,
    trace_id: str,
    condition_id: str,
    market_slug: str | None,
    default_token_id: str | None,
    decision: StrategyDecision,
) -> ManagedOrderIntent | None:
    resolved_token_id = decision.token_id or default_token_id
    if resolved_token_id is None:
        return None
    resolved_market_slug = decision.market_slug or market_slug
    if decision.action == StrategyAction.BUY:
        if (
            decision.price is None
            or decision.amount_usdc is None
            or decision.amount_usdc <= Decimal("0")
        ):
            return None
        return BuyOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=resolved_token_id,
            price=decision.price,
            amount_usdc=decision.amount_usdc,
            order_type=decision.order_type or OrderType.FAK,
            market_slug=resolved_market_slug,
        )
    if decision.action == StrategyAction.SELL:
        if decision.price is None or decision.size_shares is None or decision.size_shares <= Decimal("0"):
            return None
        return SellOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=resolved_token_id,
            price=decision.price,
            size_shares=decision.size_shares,
            order_type=decision.order_type or OrderType.GTC,
            market_slug=resolved_market_slug,
        )
    if decision.action == StrategyAction.CANCEL:
        if not decision.order_id:
            return None
        return CancelOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=resolved_token_id,
            order_id=decision.order_id,
            market_slug=resolved_market_slug,
            reason=decision.reason,
        )
    if decision.action == StrategyAction.REPLACE:
        if (
            not decision.order_id
            or decision.price is None
            or decision.size_shares is None
            or decision.size_shares <= Decimal("0")
        ):
            return None
        return ReplaceOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=resolved_token_id,
            order_id=decision.order_id,
            new_price=decision.price,
            size_shares=decision.size_shares,
            market_slug=resolved_market_slug,
            reason=decision.reason,
        )
    return None
