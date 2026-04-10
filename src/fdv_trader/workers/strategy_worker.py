from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable
from uuid import uuid4

from fdv_trader.app.strategy_service import StrategyEntryPlan, StrategyService
from fdv_trader.app.trading_service import TradingReviewResult, TradingService
from fdv_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from fdv_trader.domain.order import Order
from fdv_trader.domain.position import Position
from fdv_trader.runtime.event_bus import EventBus

PositionsProvider = Callable[[], Iterable[Position]]
OpenOrdersProvider = Callable[[], Iterable[Order]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrategyWorker:
    priority = "P0"

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        strategy_service: StrategyService | None = None,
        trading_service: TradingService | None = None,
        positions_provider: PositionsProvider | None = None,
        open_orders_provider: OpenOrdersProvider | None = None,
        portfolio_budget_usdc: Decimal = Decimal("0"),
        available_usdc: Decimal | None = None,
        max_order_usdc: Decimal = Decimal("0"),
        max_market_usdc: Decimal = Decimal("0"),
        max_total_usdc: Decimal = Decimal("0"),
        entry_no_price_max: Decimal = Decimal("0.60"),
        min_liquidity_usdc: Decimal = Decimal("0"),
        max_spread: Decimal | None = None,
        balance_usdc: Decimal | None = None,
        allowance_usdc: Decimal | None = None,
        max_open_orders: int | None = None,
        order_retry_limit: int | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._strategy_service = strategy_service or StrategyService()
        self._trading_service = trading_service or TradingService()
        self._positions_provider = positions_provider or (lambda: ())
        self._open_orders_provider = open_orders_provider or (lambda: ())
        self._portfolio_budget_usdc = portfolio_budget_usdc
        self._available_usdc = available_usdc
        self._max_order_usdc = max_order_usdc
        self._max_market_usdc = max_market_usdc
        self._max_total_usdc = max_total_usdc
        self._entry_no_price_max = entry_no_price_max
        self._min_liquidity_usdc = min_liquidity_usdc
        self._max_spread = max_spread
        self._balance_usdc = balance_usdc
        self._allowance_usdc = allowance_usdc
        self._max_open_orders = max_open_orders
        self._order_retry_limit = order_retry_limit

    async def run(self) -> None:
        if self._event_bus is None:
            raise RuntimeError("StrategyWorker requires an EventBus to run")
        while True:
            await self.run_once()

    async def run_once(self) -> "StrategyWorkerResult | None":
        if self._event_bus is None:
            raise RuntimeError("StrategyWorker requires an EventBus to run")
        event = await self._event_bus.next_trading_event()
        return await self.process_event(event)

    async def process_event(self, event: DomainEvent) -> "StrategyWorkerResult | None":
        event_name = str(event.event_type)
        if event_name != DomainEventType.ENTRY_PRICE_TOUCHED.value:
            return None

        positions = tuple(self._positions_provider())
        open_orders = tuple(self._open_orders_provider())
        plan = self._strategy_service.build_entry_plan(
            trace_id=event.trace_id,
            condition_id=event.condition_id,
            token_id=event.token_id,
            portfolio_budget_usdc=self._portfolio_budget_usdc,
            available_usdc=self._available_usdc,
            max_order_usdc=self._max_order_usdc,
            max_market_usdc=self._max_market_usdc,
            max_total_usdc=self._max_total_usdc,
            positions=positions,
            open_orders=open_orders,
            entry_no_price_max=self._entry_no_price_max,
            min_liquidity_usdc=self._min_liquidity_usdc,
            max_spread=self._max_spread,
        )
        if not plan.ready_to_trade or plan.intent is None or plan.market is None or plan.orderbook is None:
            skipped = DomainEvent(
                trace_id=plan.trace_id,
                event_type=DomainEventType.SKIPPED,
                event_id=uuid4().hex,
                market_slug=plan.market.market_slug if plan.market is not None else event.market_slug,
                condition_id=plan.market.condition_id if plan.market is not None else event.condition_id,
                token_id=event.token_id,
                reason=plan.reason or "allocation_skipped",
                created_at=_utc_now(),
                payload={
                    "entry_event_id": event.event_id,
                    "allocation_plan": _serialize_allocation_plan(plan),
                    "allocation": _serialize_allocation(plan),
                    "reason": plan.reason or "allocation_skipped",
                },
            )
            await self._publish(OutboxPriority.P0, skipped)
            return StrategyWorkerResult(
                entry_event=event,
                plan=plan,
                review=None,
                emitted_event=skipped,
            )

        focus_position = _match_position(positions, plan.market.condition_id, plan.market.no_token_id)
        focus_open_orders = _match_open_orders(open_orders, plan.market.condition_id, plan.market.no_token_id)
        review = await self._trading_service.review_intent(
            plan.intent,
            market=plan.market,
            orderbook=plan.orderbook,
            position=focus_position,
            open_orders=focus_open_orders,
            allocation_plan=plan.allocation_plan,
            classification_passed=True,
            balance_usdc=self._balance_usdc,
            allowance_usdc=self._allowance_usdc,
            max_order_usdc=self._max_order_usdc,
            max_market_usdc=self._max_market_usdc,
            max_total_usdc=self._max_total_usdc,
            max_open_orders=self._max_open_orders,
            order_retry_limit=self._order_retry_limit,
            entry_no_price_max=self._entry_no_price_max,
            min_liquidity_usdc=self._min_liquidity_usdc,
            max_spread=self._max_spread,
        )
        result_event = DomainEvent(
            trace_id=plan.trace_id,
            event_type=(
                DomainEventType.RISK_CHECK_PASSED
                if review.risk_decision.passed
                else DomainEventType.RISK_CHECK_FAILED
            ),
            event_id=uuid4().hex,
            market_slug=plan.market.market_slug,
            condition_id=plan.market.condition_id,
            token_id=plan.market.no_token_id,
            reason=review.risk_decision.reason,
            created_at=_utc_now(),
            payload={
                "entry_event_id": event.event_id,
                "allocation_plan": _serialize_allocation_plan(plan),
                "allocation": _serialize_allocation(plan),
                "intent": _serialize_intent(plan.intent),
                "risk_decision": _serialize_risk_review(review),
            },
        )
        await self._publish(OutboxPriority.P0, result_event)
        return StrategyWorkerResult(
            entry_event=event,
            plan=plan,
            review=review,
            emitted_event=result_event,
        )

    async def _publish(self, priority: OutboxPriority, event: DomainEvent) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(priority, event)


@dataclass(frozen=True, slots=True)
class StrategyWorkerResult:
    entry_event: DomainEvent
    plan: StrategyEntryPlan
    review: TradingReviewResult | None
    emitted_event: DomainEvent


def _match_position(
    positions: tuple[Position, ...],
    condition_id: str,
    token_id: str,
) -> Position | None:
    for position in positions:
        if position.condition_id == condition_id and position.token_id == token_id:
            return position
    return None


def _match_open_orders(
    open_orders: tuple[Order, ...],
    condition_id: str,
    token_id: str,
) -> tuple[Order, ...]:
    return tuple(
        order
        for order in open_orders
        if order.condition_id == condition_id and order.token_id == token_id
    )


def _serialize_allocation_plan(plan: StrategyEntryPlan) -> dict[str, object]:
    return {
        "trace_id": plan.allocation_plan.trace_id,
        "total_budget_usdc": str(plan.allocation_plan.total_budget_usdc),
        "allocated_budget_usdc": str(plan.allocation_plan.allocated_budget_usdc),
        "released_budget_usdc": str(plan.allocation_plan.released_budget_usdc),
        "eligible_market_count": plan.eligible_market_count,
        "reason": plan.allocation_plan.reason,
    }


def _serialize_allocation(plan: StrategyEntryPlan) -> dict[str, object] | None:
    if plan.allocation is None:
        return None
    return {
        "condition_id": plan.allocation.condition_id,
        "target_budget_usdc": str(plan.allocation.target_budget_usdc),
        "buy_budget_usdc": str(plan.allocation.buy_budget_usdc),
        "current_exposure_usdc": str(plan.allocation.current_exposure_usdc),
        "released_budget_usdc": str(plan.allocation.released_budget_usdc),
        "reason": plan.allocation.reason,
        "release_reason": plan.allocation.release_reason,
    }


def _serialize_intent(intent: OrderIntent) -> dict[str, object]:
    return {
        "trace_id": intent.trace_id,
        "condition_id": intent.condition_id,
        "token_id": intent.token_id,
        "side": intent.side.value,
        "order_type": intent.order_type.value,
        "price": str(intent.price),
        "amount_usdc": None if intent.amount_usdc is None else str(intent.amount_usdc),
        "market_slug": intent.market_slug,
    }


def _serialize_risk_review(review: TradingReviewResult) -> dict[str, object]:
    return {
        "passed": review.risk_decision.passed,
        "reason": review.risk_decision.reason,
        "failed_field": review.risk_decision.failed_field,
        "suggested_action": review.risk_decision.suggested_action,
        "retryable": review.risk_decision.retryable,
        "submitted": review.submitted,
        "submission_error": review.submission_error,
        "checks": tuple(
            {
                "name": check.name,
                "passed": check.passed,
                "reason": check.reason,
                "field": check.field,
                "suggested_action": check.suggested_action,
                "retryable": check.retryable,
            }
            for check in review.risk_decision.checks
        ),
    }
