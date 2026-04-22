from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Iterable, Mapping
from uuid import uuid4

from polymarket_trader.app.strategy_service import StrategyEntryPlan, StrategyService
from polymarket_trader.app.trading_service import TradingReviewResult, TradingService
from polymarket_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from polymarket_trader.domain.market import Market, MarketOutcome
from polymarket_trader.domain.order import (
    CancelOrderIntent,
    ManagedOrderIntent,
    Order,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    ReplaceOrderIntent,
    SellOrderIntent,
)
from polymarket_trader.domain.position import Position
from polymarket_trader.domain.state_machine import MarketLifecycle
from polymarket_trader.runtime.account_state import AccountSnapshot, AccountStateStore
from polymarket_trader.runtime.event_bus import EventBus
from polymarket_trader.extension_api import MarketTokenView, StrategyContext

PositionsProvider = Callable[[], Iterable[Position]]
OpenOrdersProvider = Callable[[], Iterable[Order]]

_SELF_ORIGIN = "strategy_worker"


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
        account_state_store: AccountStateStore | None = None,
        portfolio_budget_usdc: Decimal = Decimal("0"),
        available_usdc: Decimal | None = None,
        max_order_usdc: Decimal = Decimal("0"),
        max_market_usdc: Decimal = Decimal("0"),
        max_total_usdc: Decimal = Decimal("0"),
        balance_usdc: Decimal | None = None,
        allowance_usdc: Decimal | None = None,
        max_open_orders: int | None = None,
        order_retry_limit: int | None = None,
    ) -> None:
        self._event_bus = event_bus
        if strategy_service is None:
            raise ValueError("strategy_service is required")
        self._strategy_service = strategy_service
        self._trading_service = trading_service or TradingService()
        self._account_state_store = account_state_store
        self._positions_provider = positions_provider or self._build_positions_provider()
        self._open_orders_provider = open_orders_provider or self._build_open_orders_provider()
        self._portfolio_budget_usdc = portfolio_budget_usdc
        self._available_usdc = available_usdc
        self._max_order_usdc = max_order_usdc
        self._max_market_usdc = max_market_usdc
        self._max_total_usdc = max_total_usdc
        self._balance_usdc = balance_usdc
        self._allowance_usdc = allowance_usdc
        self._max_open_orders = max_open_orders
        self._order_retry_limit = order_retry_limit
        self._market_lifecycle: dict[str, MarketLifecycle] = {}

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
        if _is_self_emitted(event):
            return None

        event_name = str(event.event_type)
        snapshot = self._snapshot()
        if event_name == DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value:
            return await self._handle_orderbook_snapshot_updated(event, snapshot)

        order_result = _coerce_order_result_from_event(event)
        if order_result is not None:
            return await self._handle_order_result(
                source_event=event,
                order_result=order_result,
                snapshot=snapshot,
            )

        if event_name == DomainEventType.POSITION_UPDATED.value:
            return await self._handle_position_updated(event, snapshot)

        return None

    async def _handle_orderbook_snapshot_updated(
        self,
        event: DomainEvent,
        snapshot: AccountSnapshot | None,
    ) -> "StrategyWorkerResult | None":
        plan = self._strategy_service.build_entry_plan(
            trace_id=event.trace_id,
            condition_id=event.condition_id,
            token_id=event.token_id,
            account_snapshot=snapshot,
            portfolio_budget_usdc=self._portfolio_budget_usdc,
            available_usdc=(
                self._available_usdc if self._available_usdc is not None else _snapshot_balance(snapshot)
            ),
            max_order_usdc=self._max_order_usdc,
            max_market_usdc=self._max_market_usdc,
            max_total_usdc=self._max_total_usdc,
            positions=(snapshot.positions if snapshot is not None else tuple(self._positions_provider())),
            open_orders=(
                snapshot.open_orders if snapshot is not None else tuple(self._open_orders_provider())
            ),
        )
        if plan.market is None or plan.orderbook is None or event.token_id != plan.orderbook.token_id:
            return None

        state = self._state_for_market(plan.market)
        if state is None:
            self._transition_market(plan.market, MarketLifecycle.WATCHING_ORDERBOOK)
        elif state != MarketLifecycle.WATCHING_ORDERBOOK:
            return None
        return await self._execute_entry_plan(event=event, snapshot=snapshot, plan=plan)

    async def _execute_entry_plan(
        self,
        *,
        event: DomainEvent,
        snapshot: AccountSnapshot | None,
        plan: StrategyEntryPlan,
    ) -> "StrategyWorkerResult":
        positions = snapshot.positions if snapshot is not None else tuple(self._positions_provider())
        open_orders = (
            snapshot.open_orders if snapshot is not None else tuple(self._open_orders_provider())
        )
        if snapshot is not None and not snapshot.allow_new_entries:
            skipped = await self._publish(
                DomainEventType.SKIPPED,
                trace_id=event.trace_id,
                market_slug=event.market_slug,
                condition_id=event.condition_id,
                token_id=event.token_id,
                reason="entry_paused",
                payload={
                    "entry_event_id": event.event_id,
                    "origin": _SELF_ORIGIN,
                    "reason": "entry_paused",
                    "account_snapshot": _serialize_snapshot(snapshot),
                },
            )
            self._transition_market(plan.market, MarketLifecycle.PAUSED if plan.market else None)
            return StrategyWorkerResult(
                entry_event=event,
                plan=plan,
                review=None,
                emitted_event=skipped,
                state_after=self._state_for_market(plan.market),
            )

        if not plan.ready_to_trade or plan.intent is None or plan.market is None or plan.orderbook is None:
            self._transition_market(plan.market, MarketLifecycle.WATCHING_ORDERBOOK if plan.market else None)
            return StrategyWorkerResult(
                entry_event=event,
                plan=plan,
                review=None,
                emitted_event=None,
                state_after=self._state_for_market(plan.market),
            )

        focus_token_id = plan.intent.token_id
        focus_position = _match_position(positions, plan.market.condition_id, focus_token_id)
        focus_open_orders = _match_open_orders(open_orders, plan.market.condition_id, focus_token_id)
        self._transition_market(plan.market, MarketLifecycle.ENTRY_SUBMITTING)
        review = await self._trading_service.review_intent(
            plan.intent,
            market=plan.market,
            orderbook=plan.orderbook,
            position=focus_position,
            open_orders=focus_open_orders,
            allocation_plan=plan.allocation_plan,
            classification_passed=True,
            balance_usdc=self._balance_usdc if self._balance_usdc is not None else _snapshot_balance(snapshot),
            allowance_usdc=(
                self._allowance_usdc if self._allowance_usdc is not None else _snapshot_allowance(snapshot)
            ),
            max_order_usdc=self._max_order_usdc,
            max_market_usdc=self._max_market_usdc,
            max_total_usdc=self._max_total_usdc,
            max_open_orders=self._max_open_orders,
            order_retry_limit=self._order_retry_limit,
            operation=plan.intent.side.value.lower(),
        )
        risk_event = await self._publish(
            DomainEventType.RISK_CHECK_PASSED
            if review.risk_decision is not None and review.risk_decision.passed
            else DomainEventType.RISK_CHECK_FAILED,
            trace_id=plan.trace_id,
            market_slug=plan.market.market_slug,
            condition_id=plan.market.condition_id,
            token_id=plan.intent.token_id,
            reason="" if review.risk_decision is None else review.risk_decision.reason,
            payload={
                "entry_event_id": event.event_id,
                "origin": _SELF_ORIGIN,
                "allocation_plan": _serialize_allocation_plan(plan),
                "allocation": _serialize_allocation(plan),
                "intent": _serialize_intent(plan.intent),
                "review": _serialize_review(review),
            },
        )
        result = await self._handle_order_result(
            source_event=event,
            order_result=review.order_result,
            snapshot=snapshot,
            execution=review,
            plan=plan,
        )
        return StrategyWorkerResult(
            entry_event=event,
            plan=plan,
            review=review,
            emitted_event=risk_event,
            emitted_events=(risk_event, *result.emitted_events),
            follow_up_intents=result.follow_up_intents,
            follow_up_reviews=result.follow_up_reviews,
            state_before=result.state_before,
            state_after=result.state_after,
        )

    async def _handle_order_result(
        self,
        *,
        source_event: DomainEvent,
        order_result: OrderResult | None,
        snapshot: AccountSnapshot | None,
        execution: TradingReviewResult | None = None,
        plan: StrategyEntryPlan | None = None,
    ) -> "StrategyWorkerResult":
        if order_result is None:
            order_result = _coerce_order_result_from_event(source_event)
        if order_result is None:
            return StrategyWorkerResult(
                entry_event=source_event,
                plan=plan,
                review=execution,
                emitted_event=source_event,
                state_after=self._state_for_market(plan.market if plan is not None else None),
            )

        state_before = self._state_for_market_by_key(order_result.condition_id)
        result_event_type = _result_event_type(order_result)
        result_event = await self._publish(
            result_event_type,
            trace_id=order_result.trace_id,
            market_slug=order_result.market_slug,
            condition_id=order_result.condition_id,
            token_id=order_result.token_id,
            reason=order_result.reason,
            payload={
                "origin": _SELF_ORIGIN,
                "source_event_id": source_event.event_id,
                "operation": execution.operation if execution is not None else "result",
                "order_result": _serialize_order_result(order_result),
                "execution": None if execution is None else _serialize_review(execution),
            },
        )
        self._transition_from_order_result(order_result)
        follow_up_intents: list[ManagedOrderIntent] = []
        follow_up_results: list[TradingReviewResult] = []
        active_snapshot = snapshot

        if order_result.side == OrderSide.BUY and order_result.status in {
            OrderResultStatus.FULL_FILL,
            OrderResultStatus.PARTIAL_FILL,
            OrderResultStatus.NO_FILL,
        }:
            self._update_account_state_from_buy(order_result, snapshot=snapshot)
            active_snapshot = (
                self._account_state_store.snapshot()
                if self._account_state_store is not None
                else snapshot
            )
        elif (
            execution is not None
            and isinstance(execution.intent, SellOrderIntent)
            and order_result.side == OrderSide.SELL
        ):
            self._update_account_state_from_sell(
                order_result,
                snapshot=snapshot,
                intent=execution.intent,
            )
            active_snapshot = (
                self._account_state_store.snapshot()
                if self._account_state_store is not None
                else snapshot
            )

        if order_result.side is not None and order_result.side.value == "BUY":
            if order_result.status in {OrderResultStatus.FULL_FILL, OrderResultStatus.PARTIAL_FILL}:
                released_budget_usdc = _released_budget(order_result)
                await self._publish(
                    DomainEventType.ORDER_STATE_UPDATED,
                    trace_id=order_result.trace_id,
                    market_slug=order_result.market_slug,
                    condition_id=order_result.condition_id,
                    token_id=order_result.token_id,
                    reason="budget_released",
                    payload={
                        "origin": _SELF_ORIGIN,
                        "state": "entry_result_updated",
                        "released_budget_usdc": str(released_budget_usdc),
                        "order_result": _serialize_order_result(order_result),
                    },
                )
            elif order_result.status == OrderResultStatus.NO_FILL:
                released_budget_usdc = _released_budget(order_result)
                await self._publish(
                    DomainEventType.ORDER_STATE_UPDATED,
                    trace_id=order_result.trace_id,
                    market_slug=order_result.market_slug,
                    condition_id=order_result.condition_id,
                    token_id=order_result.token_id,
                    reason="budget_released",
                    payload={
                        "origin": _SELF_ORIGIN,
                        "state": "no_fill_released",
                        "released_budget_usdc": str(released_budget_usdc),
                        "order_result": _serialize_order_result(order_result),
                    },
                )
                self._transition_market_by_result(order_result, MarketLifecycle.ENTRY_READY)
            elif _has_unexpected_resting_order(order_result):
                await self._publish(
                    DomainEventType.ORDER_STATE_UPDATED,
                    trace_id=order_result.trace_id,
                    market_slug=order_result.market_slug,
                    condition_id=order_result.condition_id,
                    token_id=order_result.token_id,
                    reason=order_result.reason or "unexpected_resting_order",
                    payload={
                        "origin": _SELF_ORIGIN,
                        "state": "unexpected_resting_order",
                        "order_result": _serialize_order_result(order_result),
                    },
                )
                cancel_intent = CancelOrderIntent(
                    trace_id=order_result.trace_id,
                    condition_id=order_result.condition_id,
                    token_id=order_result.token_id,
                    order_id=order_result.order_id or f"{order_result.trace_id}:{order_result.condition_id}:{order_result.token_id}",
                    market_slug=order_result.market_slug,
                    idempotency_key=f"{order_result.trace_id}:{order_result.condition_id}:{order_result.token_id}:cancel",
                    reason="unexpected_resting_order",
                )
                follow_up_intents.append(cancel_intent)
                cancel_review = await self._trading_service.cancel(cancel_intent)
                follow_up_results.append(cancel_review)
                await self._publish(
                    DomainEventType.ORDER_CANCEL_REQUESTED,
                    trace_id=cancel_intent.trace_id,
                    market_slug=cancel_intent.market_slug,
                    condition_id=cancel_intent.condition_id,
                    token_id=cancel_intent.token_id,
                    reason=cancel_intent.reason,
                    payload={
                        "origin": _SELF_ORIGIN,
                        "cancel_intent": _serialize_control_intent(cancel_intent),
                        "order_result": _serialize_order_result(order_result),
                    },
                )
                if (
                    cancel_review.order_result is not None
                    and cancel_review.order_result.status == OrderResultStatus.CANCELLED
                ):
                    await self._publish(
                        DomainEventType.ORDER_CANCELLED,
                        trace_id=cancel_intent.trace_id,
                        market_slug=cancel_intent.market_slug,
                        condition_id=cancel_intent.condition_id,
                        token_id=cancel_intent.token_id,
                        reason=cancel_review.order_result.reason,
                        payload={
                            "origin": _SELF_ORIGIN,
                            "cancel_review": _serialize_review(cancel_review),
                            "order_result": _serialize_order_result(cancel_review.order_result),
                        },
                    )
                    self._transition_from_order_result(cancel_review.order_result)
                self._pause_market(order_result.condition_id, reason="unexpected_resting_order")
            elif order_result.status in {OrderResultStatus.REJECTED, OrderResultStatus.FAILED, OrderResultStatus.UNKNOWN_TIMEOUT}:
                await self._publish(
                    DomainEventType.ORDER_STATE_UPDATED,
                    trace_id=order_result.trace_id,
                    market_slug=order_result.market_slug,
                    condition_id=order_result.condition_id,
                    token_id=order_result.token_id,
                    reason=order_result.reason,
                    payload={
                        "origin": _SELF_ORIGIN,
                        "state": "rejected",
                        "order_result": _serialize_order_result(order_result),
                    },
                )
                self._transition_market_by_result(order_result, MarketLifecycle.ENTRY_REJECTED)

        resolved_market = self._strategy_service._resolve_market(
            condition_id=order_result.condition_id,
            token_id=order_result.token_id,
        )
        follow_up_decisions = self._strategy_service.decide_follow_up(
            StrategyContext(
                trace_id=order_result.trace_id,
                market=resolved_market,
                token_id=order_result.token_id,
                market_token_views=tuple(
                    MarketTokenView(
                        token_id=outcome.token_id,
                        outcome=outcome.outcome,
                    )
                    for outcome in (
                        ()
                        if resolved_market is None
                        else resolved_market.outcomes
                    )
                ),
                account_snapshot=active_snapshot,
                position=_snapshot_position(
                    active_snapshot,
                    order_result.condition_id,
                    order_result.token_id,
                ),
                open_orders=(
                    active_snapshot.open_orders_for_market(
                        order_result.condition_id,
                        order_result.token_id,
                    )
                    if active_snapshot is not None
                    else ()
                ),
                order_result=order_result,
            )
        )
        for decision in follow_up_decisions:
            intent = self._strategy_service.build_intent_from_decision(
                trace_id=order_result.trace_id,
                condition_id=order_result.condition_id,
                market_slug=order_result.market_slug,
                default_token_id=order_result.token_id,
                decision=decision,
            )
            if intent is None:
                continue
            follow_up_intents.append(intent)
            follow_up_review = await self._execute_managed_intent(
                intent,
                snapshot=active_snapshot,
            )
            follow_up_results.append(follow_up_review)
            follow_up_event = await self._publish(
                DomainEventType.ORDER_SUBMITTED,
                trace_id=intent.trace_id,
                market_slug=intent.market_slug,
                condition_id=intent.condition_id,
                token_id=intent.token_id,
                reason="" if follow_up_review.order_result is None else follow_up_review.order_result.reason,
                payload={
                    "origin": _SELF_ORIGIN,
                    "phase": "follow_up",
                    "source_order_result": _serialize_order_result(order_result),
                    "intent": _serialize_intent(intent),
                    "review": _serialize_review(follow_up_review),
                },
            )
            if follow_up_review.order_result is not None:
                self._transition_from_order_result(follow_up_review.order_result)
                if isinstance(intent, SellOrderIntent):
                    self._update_account_state_from_sell(
                        follow_up_review.order_result,
                        snapshot=active_snapshot,
                        intent=intent,
                    )
                self._update_account_state_from_order_result(
                    follow_up_review.order_result,
                    snapshot=active_snapshot,
                )
                active_snapshot = (
                    self._account_state_store.snapshot()
                    if self._account_state_store is not None
                    else active_snapshot
                )
            result_event = follow_up_event

        self._update_account_state_from_order_result(order_result, snapshot=snapshot)
        return StrategyWorkerResult(
            entry_event=source_event,
            plan=plan,
            review=execution,
            emitted_event=result_event,
            emitted_events=(result_event,),
            follow_up_intents=tuple(follow_up_intents),
            follow_up_reviews=tuple(follow_up_results),
            state_before=state_before,
            state_after=self._state_for_market_by_key(order_result.condition_id),
        )

    async def _handle_position_updated(
        self,
        event: DomainEvent,
        snapshot: AccountSnapshot | None,
    ) -> "StrategyWorkerResult":
        if snapshot is None:
            return StrategyWorkerResult(
                entry_event=event,
                plan=None,
                review=None,
                emitted_event=event,
                state_after=None,
            )
        market = self._market_from_snapshot_position(snapshot, event.condition_id, event.token_id)
        if market is not None:
            self._transition_market(market, MarketLifecycle.POSITION_OPEN)
        return StrategyWorkerResult(
            entry_event=event,
            plan=None,
            review=None,
            emitted_event=event,
            state_after=self._state_for_market(market),
        )

    async def _publish(
        self,
        event_type: DomainEventType,
        *,
        trace_id: str,
        market_slug: str | None,
        condition_id: str | None,
        token_id: str | None,
        reason: str = "",
        payload: Mapping[str, object] | None = None,
    ) -> DomainEvent:
        payload_dict = {"origin": _SELF_ORIGIN}
        if payload is not None:
            payload_dict.update(dict(payload))
        event = DomainEvent(
            trace_id=trace_id,
            event_type=event_type,
            event_id=uuid4().hex,
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
            reason=reason,
            created_at=_utc_now(),
            payload=payload_dict,
        )
        if self._event_bus is not None:
            await self._event_bus.publish(OutboxPriority.P0, event)
        return event

    def _snapshot(self) -> AccountSnapshot | None:
        if self._account_state_store is not None:
            return self._account_state_store.snapshot()
        if self._balance_usdc is None and self._allowance_usdc is None:
            return None
        return AccountSnapshot(
            balance_usdc=self._balance_usdc or Decimal("0"),
            allowance_usdc=self._allowance_usdc or Decimal("0"),
            positions=tuple(self._positions_provider()),
            open_orders=tuple(self._open_orders_provider()),
            allow_new_entries=True,
        )

    def _build_positions_provider(self) -> PositionsProvider:
        if self._account_state_store is None:
            return lambda: ()
        return lambda: self._account_state_store.snapshot().positions

    def _build_open_orders_provider(self) -> OpenOrdersProvider:
        if self._account_state_store is None:
            return lambda: ()
        return lambda: self._account_state_store.snapshot().open_orders

    def _transition_market(self, market: Market | None, lifecycle: MarketLifecycle | None) -> None:
        if market is None or lifecycle is None:
            return
        self._market_lifecycle[market.condition_id] = lifecycle

    def _transition_market_by_result(self, order_result: OrderResult, lifecycle: MarketLifecycle) -> None:
        market = _market_from_result(order_result)
        self._transition_market(market, lifecycle)

    def _transition_from_order_result(self, order_result: OrderResult) -> None:
        if order_result.side is None:
            return
        side = str(order_result.side).upper()
        if side == "BUY":
            if order_result.status in {OrderResultStatus.FULL_FILL, OrderResultStatus.PARTIAL_FILL}:
                self._transition_market_by_result(order_result, MarketLifecycle.POSITION_OPEN)
            elif order_result.status == OrderResultStatus.LIVE:
                self._transition_market_by_result(order_result, MarketLifecycle.PAUSED)
            elif order_result.status == OrderResultStatus.NO_FILL:
                self._transition_market_by_result(order_result, MarketLifecycle.ENTRY_READY)
            elif order_result.status in {OrderResultStatus.REJECTED, OrderResultStatus.FAILED, OrderResultStatus.UNKNOWN_TIMEOUT}:
                self._transition_market_by_result(order_result, MarketLifecycle.ENTRY_REJECTED)
        elif side == "SELL":
            if order_result.status in {OrderResultStatus.LIVE, OrderResultStatus.PARTIAL_FILL}:
                self._transition_market_by_result(order_result, MarketLifecycle.FOLLOW_UP_ORDER_OPEN)
            elif order_result.status == OrderResultStatus.FULL_FILL:
                self._transition_market_by_result(order_result, MarketLifecycle.POSITION_OPEN)

    def _pause_market(self, condition_id: str | None, *, reason: str) -> None:
        if condition_id is None:
            return
        self._market_lifecycle[condition_id] = MarketLifecycle.PAUSED
        if self._account_state_store is not None:
            self._account_state_store.pause_market(condition_id, reason=reason)

    def _state_for_market(self, market: Market | None) -> MarketLifecycle | None:
        if market is None:
            return None
        return self._market_lifecycle.get(market.condition_id)

    def _state_for_market_by_key(self, condition_id: str | None) -> MarketLifecycle | None:
        if condition_id is None:
            return None
        return self._market_lifecycle.get(condition_id)

    def _update_account_state_from_buy(
        self,
        order_result: OrderResult,
        *,
        snapshot: AccountSnapshot | None,
    ) -> None:
        if self._account_state_store is None:
            return
        if order_result.status not in {
            OrderResultStatus.FULL_FILL,
            OrderResultStatus.PARTIAL_FILL,
            OrderResultStatus.NO_FILL,
        }:
            return
        position = _snapshot_position(snapshot, order_result.condition_id, order_result.token_id)
        filled_shares = _filled_shares(order_result)
        spent_usdc = _spent_usdc(order_result)
        if position is None and filled_shares <= Decimal("0"):
            return
        if position is None:
            position = Position(
                condition_id=order_result.condition_id,
                token_id=order_result.token_id,
                shares=filled_shares,
                cost_usdc=spent_usdc,
                market_slug=order_result.market_slug,
                open_sell_shares=Decimal("0"),
                pending_buy_shares=Decimal("0"),
                confirmation_status=str(order_result.status),
                last_order_id=order_result.order_id,
                last_trade_id=order_result.trade_id,
                updated_at=_utc_now(),
            )
        else:
            position = Position(
                condition_id=position.condition_id,
                token_id=position.token_id,
                shares=position.shares + filled_shares,
                cost_usdc=position.cost_usdc + spent_usdc,
                market_slug=position.market_slug or order_result.market_slug,
                open_buy_shares=Decimal("0"),
                open_sell_shares=position.open_sell_shares,
                pending_buy_shares=Decimal("0"),
                confirmed_shares=position.confirmed_shares + filled_shares,
                last_order_id=order_result.order_id or position.last_order_id,
                last_trade_id=order_result.trade_id or position.last_trade_id,
                confirmation_status=str(order_result.status),
                updated_at=_utc_now(),
            )
        self._account_state_store.upsert_position(position)
        if snapshot is not None:
            self._account_state_store.update_balances(
                balance_usdc=snapshot.balance_usdc,
                allowance_usdc=snapshot.allowance_usdc,
            )

    def _update_account_state_from_sell(
        self,
        order_result: OrderResult,
        *,
        snapshot: AccountSnapshot | None,
        intent: SellOrderIntent,
    ) -> None:
        if self._account_state_store is None:
            return
        if order_result.status not in {
            OrderResultStatus.FULL_FILL,
            OrderResultStatus.PARTIAL_FILL,
            OrderResultStatus.LIVE,
        }:
            return
        current_snapshot = self._account_state_store.snapshot()
        position = _snapshot_position(current_snapshot, order_result.condition_id, order_result.token_id)
        if position is None:
            position = _snapshot_position(snapshot, order_result.condition_id, order_result.token_id)
        if position is None:
            return
        remaining_shares = order_result.remaining_shares
        if order_result.status in {OrderResultStatus.LIVE, OrderResultStatus.PARTIAL_FILL} and remaining_shares <= Decimal(
            "0"
        ):
            remaining_shares = intent.size_shares - _filled_shares(order_result)
        if remaining_shares < Decimal("0"):
            remaining_shares = Decimal("0")
        open_sell = max(position.open_sell_shares - _existing_order_size(current_snapshot, order_result), Decimal("0"))
        open_sell += remaining_shares
        if open_sell < Decimal("0"):
            open_sell = Decimal("0")
        order_id = order_result.order_id or intent.idempotency_key or f"{order_result.trace_id}:{order_result.condition_id}:{order_result.token_id}:sell"
        if order_result.status in {OrderResultStatus.LIVE, OrderResultStatus.PARTIAL_FILL}:
            self._account_state_store.upsert_order(
                Order(
                    trace_id=order_result.trace_id,
                    condition_id=order_result.condition_id,
                    token_id=order_result.token_id,
                    market_slug=position.market_slug or order_result.market_slug,
                    side=OrderSide.SELL,
                    order_type=order_result.order_type or intent.order_type,
                    price=order_result.price or intent.price,
                    size_shares=order_result.requested_size_shares or intent.size_shares,
                    filled_shares=order_result.matched_shares,
                    remaining_shares=remaining_shares,
                    notional_usdc=order_result.notional_usdc,
                    order_id=order_id,
                    trade_id=order_result.trade_id,
                    status=_order_status_from_result(order_result),
                    idempotency_key=intent.idempotency_key or order_id,
                    reason=order_result.reason,
                    post_only=intent.post_only,
                    created_at=order_result.timestamps.queued_at,
                    updated_at=order_result.timestamps.ack_at,
                )
            )
        else:
            self._account_state_store.remove_order(order_id)
        position = Position(
            condition_id=position.condition_id,
            token_id=position.token_id,
            shares=position.shares,
            cost_usdc=position.cost_usdc,
            market_slug=position.market_slug or order_result.market_slug,
            open_buy_shares=position.open_buy_shares,
            open_sell_shares=open_sell,
            pending_buy_shares=position.pending_buy_shares,
            confirmed_shares=position.confirmed_shares,
            last_order_id=order_result.order_id or position.last_order_id,
            last_trade_id=order_result.trade_id or position.last_trade_id,
            confirmation_status=str(order_result.status),
            updated_at=_utc_now(),
        )
        self._account_state_store.upsert_position(position)

    def _update_account_state_from_order_result(
        self,
        order_result: OrderResult,
        *,
        snapshot: AccountSnapshot | None,
    ) -> None:
        if self._account_state_store is None:
            return
        if _has_unexpected_resting_order(order_result):
            self._account_state_store.set_allow_new_entries(False)
            self._pause_market(order_result.condition_id, reason="unexpected_resting_order")
        if order_result.status in {OrderResultStatus.REJECTED, OrderResultStatus.FAILED, OrderResultStatus.UNKNOWN_TIMEOUT}:
            self._account_state_store.set_allow_new_entries(True)
        if snapshot is not None:
            self._account_state_store.update_balances(
                balance_usdc=snapshot.balance_usdc,
                allowance_usdc=snapshot.allowance_usdc,
            )

    def _market_from_snapshot_position(
        self,
        snapshot: AccountSnapshot,
        condition_id: str | None,
        token_id: str | None,
    ) -> Market | None:
        if condition_id is None or token_id is None:
            return None
        position = snapshot.get_position(condition_id, token_id)
        if position is None:
            return None
        market = self._strategy_service._resolve_market(condition_id=condition_id, token_id=token_id)
        return market

    async def _execute_managed_intent(
        self,
        intent: ManagedOrderIntent,
        *,
        snapshot: AccountSnapshot | None,
    ) -> TradingReviewResult:
        market = self._strategy_service._resolve_market(
            condition_id=intent.condition_id,
            token_id=intent.token_id,
        )
        if isinstance(intent, CancelOrderIntent):
            return await self._trading_service.cancel(intent)
        if isinstance(intent, ReplaceOrderIntent):
            return await self._trading_service.replace(intent)
        return await self._trading_service.review_intent(
            intent,
            market=market,
            orderbook=self._strategy_service._lookup_orderbook(intent.token_id),
            position=_snapshot_position(snapshot, intent.condition_id, intent.token_id),
            open_orders=(
                snapshot.open_orders_for_market(intent.condition_id, intent.token_id)
                if snapshot is not None
                else ()
            ),
            classification_passed=True,
            balance_usdc=self._balance_usdc if self._balance_usdc is not None else _snapshot_balance(snapshot),
            allowance_usdc=(
                self._allowance_usdc if self._allowance_usdc is not None else _snapshot_allowance(snapshot)
            ),
            max_order_usdc=self._max_order_usdc,
            max_market_usdc=self._max_market_usdc,
            max_total_usdc=self._max_total_usdc,
            max_open_orders=self._max_open_orders,
            order_retry_limit=self._order_retry_limit,
            operation=intent.side.value.lower(),
        )


@dataclass(frozen=True, slots=True)
class StrategyWorkerResult:
    entry_event: DomainEvent
    plan: StrategyEntryPlan | None
    review: TradingReviewResult | None
    emitted_event: DomainEvent
    emitted_events: tuple[DomainEvent, ...] = ()
    follow_up_intents: tuple[ManagedOrderIntent, ...] = ()
    follow_up_reviews: tuple[TradingReviewResult, ...] = ()
    state_before: MarketLifecycle | None = None
    state_after: MarketLifecycle | None = None


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


def _existing_order_size(snapshot: AccountSnapshot | None, order_result: OrderResult) -> Decimal:
    if snapshot is None:
        return Decimal("0")
    for order in snapshot.open_orders_for_market(order_result.condition_id, order_result.token_id):
        if order.order_id == order_result.order_id or (
            order_result.order_id is None and order.idempotency_key == getattr(order_result.intent, "idempotency_key", None)
        ):
            return order.remaining_shares or order.size_shares or Decimal("0")
    return Decimal("0")


def _order_status_from_result(order_result: OrderResult) -> OrderStatus:
    return {
        OrderResultStatus.FULL_FILL: OrderStatus.MATCHED,
        OrderResultStatus.PARTIAL_FILL: OrderStatus.PARTIALLY_FILLED,
        OrderResultStatus.NO_FILL: OrderStatus.NO_FILL,
        OrderResultStatus.LIVE: OrderStatus.LIVE,
        OrderResultStatus.REJECTED: OrderStatus.REJECTED,
        OrderResultStatus.FAILED: OrderStatus.FAILED,
        OrderResultStatus.CANCELLED: OrderStatus.CANCELLED,
        OrderResultStatus.UNKNOWN_TIMEOUT: OrderStatus.FAILED,
    }[order_result.status]


def _serialize_snapshot(snapshot: AccountSnapshot | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {
        "balance_usdc": str(snapshot.balance_usdc),
        "allowance_usdc": str(snapshot.allowance_usdc),
        "user_ws_connected": snapshot.user_ws_connected,
        "allow_new_entries": snapshot.allow_new_entries,
        "paused_markets": list(snapshot.paused_markets),
        "last_reconcile_at": (
            None if snapshot.last_reconcile_at is None else snapshot.last_reconcile_at.isoformat()
        ),
        "positions": [
            {
                "condition_id": position.condition_id,
                "token_id": position.token_id,
                "shares": str(position.shares),
                "cost_usdc": str(position.cost_usdc),
                "open_buy_shares": str(position.open_buy_shares),
                "open_sell_shares": str(position.open_sell_shares),
                "pending_buy_shares": str(position.pending_buy_shares),
            }
            for position in snapshot.positions
        ],
        "open_orders": [
            {
                "condition_id": order.condition_id,
                "token_id": order.token_id,
                "side": order.side.value,
                "status": order.status.value,
                "order_id": order.order_id,
                "idempotency_key": order.idempotency_key,
                "remaining_shares": (
                    None if order.remaining_shares is None else str(order.remaining_shares)
                ),
            }
            for order in snapshot.open_orders
        ],
    }


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


def _serialize_intent(intent: ManagedOrderIntent) -> dict[str, object]:
    return {
        "trace_id": intent.trace_id,
        "condition_id": intent.condition_id,
        "token_id": intent.token_id,
        "side": intent.side.value if hasattr(intent, "side") else None,
        "order_type": intent.order_type.value if hasattr(intent, "order_type") else None,
        "price": str(intent.price) if hasattr(intent, "price") and intent.price is not None else None,
        "amount_usdc": (
            None if getattr(intent, "amount_usdc", None) is None else str(intent.amount_usdc)
        ),
        "size_shares": (
            None if getattr(intent, "size_shares", None) is None else str(intent.size_shares)
        ),
        "order_id": getattr(intent, "order_id", None),
        "reason": getattr(intent, "reason", ""),
        "market_slug": intent.market_slug,
    }


def _serialize_review(review: TradingReviewResult) -> dict[str, object]:
    return {
        "operation": review.operation,
        "submitted": review.submitted,
        "submission_error": review.submission_error,
        "risk_decision": None
        if review.risk_decision is None
        else {
            "passed": review.risk_decision.passed,
            "reason": review.risk_decision.reason,
            "failed_field": review.risk_decision.failed_field,
            "suggested_action": review.risk_decision.suggested_action,
            "retryable": review.risk_decision.retryable,
        },
        "order_result": _serialize_order_result(review.order_result)
        if review.order_result is not None
        else None,
    }


def _serialize_control_intent(intent: CancelOrderIntent) -> dict[str, object]:
    return {
        "trace_id": intent.trace_id,
        "condition_id": intent.condition_id,
        "token_id": intent.token_id,
        "order_id": intent.order_id,
        "market_slug": intent.market_slug,
        "reason": intent.reason,
    }


def _serialize_order_result(order_result: OrderResult | None) -> dict[str, object] | None:
    if order_result is None:
        return None
    return {
        "trace_id": order_result.trace_id,
        "condition_id": order_result.condition_id,
        "token_id": order_result.token_id,
        "status": order_result.status.value,
        "market_slug": order_result.market_slug,
        "order_id": order_result.order_id,
        "trade_id": order_result.trade_id,
        "side": None if order_result.side is None else order_result.side.value,
        "order_type": None if order_result.order_type is None else order_result.order_type.value,
        "price": None if order_result.price is None else str(order_result.price),
        "requested_amount_usdc": None
        if order_result.requested_amount_usdc is None
        else str(order_result.requested_amount_usdc),
        "requested_size_shares": None
        if order_result.requested_size_shares is None
        else str(order_result.requested_size_shares),
        "matched_shares": str(order_result.matched_shares),
        "remaining_shares": str(order_result.remaining_shares),
        "spent_usdc": str(order_result.spent_usdc),
        "notional_usdc": str(order_result.notional_usdc),
        "reason": order_result.reason,
        "retryable": order_result.retryable,
        "raw_response_summary": order_result.raw_response_summary,
    }


def _coerce_order_result_from_event(event: DomainEvent) -> OrderResult | None:
    payload = dict(event.payload)
    order_result_payload = payload.get("order_result")
    if isinstance(order_result_payload, Mapping):
        payload = {**payload, **dict(order_result_payload)}
    status_value = payload.get("status") or payload.get("order_status")
    if status_value is None and event.event_type not in {
        DomainEventType.ORDER_MATCHED,
        DomainEventType.ORDER_PARTIALLY_FILLED,
        DomainEventType.ORDER_NO_FILL,
        DomainEventType.ORDER_REJECTED,
        DomainEventType.ORDER_CANCELLED,
        DomainEventType.ORDER_STATE_UPDATED,
        DomainEventType.FILL_RECORDED,
        DomainEventType.FOLLOW_UP_ORDER_SUBMITTED,
    }:
        return None
    status = _coerce_status(status_value, event.event_type)
    return OrderResult(
        trace_id=str(payload.get("trace_id", event.trace_id)),
        condition_id=str(payload.get("condition_id", event.condition_id or "")),
        token_id=str(payload.get("token_id", event.token_id or "")),
        status=status,
        market_slug=payload.get("market_slug", event.market_slug),
        order_id=payload.get("order_id"),
        trade_id=payload.get("trade_id"),
        side=_coerce_side(payload.get("side")),
        order_type=_coerce_order_type(payload.get("order_type")),
        price=_decimal(payload.get("price")),
        requested_amount_usdc=_decimal(payload.get("requested_amount_usdc")),
        requested_size_shares=_decimal(payload.get("requested_size_shares")),
        matched_shares=_decimal(payload.get("matched_shares")) or Decimal("0"),
        remaining_shares=_decimal(payload.get("remaining_shares")) or Decimal("0"),
        spent_usdc=_decimal(payload.get("spent_usdc")) or Decimal("0"),
        notional_usdc=_decimal(payload.get("notional_usdc")) or Decimal("0"),
        reason=str(payload.get("reason", event.reason or "")),
        retryable=bool(payload.get("retryable", False)),
        raw_response_summary=payload.get("raw_response_summary"),
    )


def _coerce_status(
    status_value: object | None,
    event_type: DomainEventType | str,
) -> OrderResultStatus:
    if isinstance(status_value, OrderResultStatus):
        return status_value
    if isinstance(status_value, str):
        try:
            return OrderResultStatus(status_value)
        except ValueError:
            pass
    event_name = str(event_type)
    if event_name == DomainEventType.ORDER_MATCHED.value:
        return OrderResultStatus.FULL_FILL
    if event_name == DomainEventType.ORDER_PARTIALLY_FILLED.value:
        return OrderResultStatus.PARTIAL_FILL
    if event_name == DomainEventType.ORDER_NO_FILL.value:
        return OrderResultStatus.NO_FILL
    if event_name == DomainEventType.ORDER_CANCELLED.value:
        return OrderResultStatus.CANCELLED
    if event_name == DomainEventType.ORDER_REJECTED.value:
        return OrderResultStatus.REJECTED
    if event_name == DomainEventType.UNEXPECTED_RESTING_ORDER_DETECTED.value:
        return OrderResultStatus.LIVE
    return OrderResultStatus.UNKNOWN_TIMEOUT


def _coerce_side(value: object | None):
    if value is None:
        return None
    try:
        from polymarket_trader.domain.order import OrderSide

        if isinstance(value, OrderSide):
            return value
        return OrderSide(str(value))
    except Exception:
        return None


def _coerce_order_type(value: object | None):
    if value is None:
        return None
    try:
        from polymarket_trader.domain.order import OrderType

        if isinstance(value, OrderType):
            return value
        return OrderType(str(value))
    except Exception:
        return None


def _decimal(value: object | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _filled_shares(order_result: OrderResult) -> Decimal:
    if order_result.matched_shares > Decimal("0"):
        return order_result.matched_shares
    if order_result.requested_size_shares is not None:
        return order_result.requested_size_shares - order_result.remaining_shares
    if order_result.notional_usdc > Decimal("0") and order_result.price and order_result.price > Decimal("0"):
        return order_result.notional_usdc / order_result.price
    return Decimal("0")


def _released_budget(order_result: OrderResult) -> Decimal:
    requested = order_result.requested_amount_usdc or order_result.notional_usdc
    released = requested - order_result.spent_usdc
    if released < Decimal("0"):
        return Decimal("0")
    return released


def _has_unexpected_resting_order(order_result: OrderResult) -> bool:
    return (
        order_result.order_type == OrderType.FAK
        and (order_result.has_resting_order or order_result.status == OrderResultStatus.LIVE)
    )


def _spent_usdc(order_result: OrderResult) -> Decimal:
    if order_result.spent_usdc > Decimal("0"):
        return order_result.spent_usdc
    if order_result.price is not None and order_result.matched_shares > Decimal("0"):
        return order_result.price * order_result.matched_shares
    return Decimal("0")


def _snapshot_balance(snapshot: AccountSnapshot | None) -> Decimal:
    if snapshot is None:
        return Decimal("0")
    return snapshot.balance_usdc


def _snapshot_allowance(snapshot: AccountSnapshot | None) -> Decimal:
    if snapshot is None:
        return Decimal("0")
    return snapshot.allowance_usdc


def _snapshot_position(
    snapshot: AccountSnapshot | None,
    condition_id: str,
    token_id: str,
) -> Position | None:
    if snapshot is None:
        return None
    return snapshot.get_position(condition_id, token_id)


def _market_from_result(order_result: OrderResult) -> Market | None:
    return Market(
        condition_id=order_result.condition_id,
        market_slug=order_result.market_slug or order_result.token_id,
        outcomes=(
            MarketOutcome(
                token_id=order_result.token_id,
                outcome="EXECUTED_OUTCOME",
            ),
        ),
    )


def _result_event_type(order_result: OrderResult) -> DomainEventType:
    if order_result.status == OrderResultStatus.FULL_FILL:
        return DomainEventType.ORDER_MATCHED
    if order_result.status == OrderResultStatus.PARTIAL_FILL:
        return DomainEventType.ORDER_PARTIALLY_FILLED
    if order_result.status == OrderResultStatus.NO_FILL:
        return DomainEventType.ORDER_NO_FILL
    if order_result.status == OrderResultStatus.REJECTED:
        return DomainEventType.ORDER_REJECTED
    if order_result.status == OrderResultStatus.CANCELLED:
        return DomainEventType.ORDER_CANCELLED
    if order_result.status == OrderResultStatus.LIVE:
        return DomainEventType.ORDER_STATE_UPDATED
    return DomainEventType.ERROR


def _is_self_emitted(event: DomainEvent) -> bool:
    return event.payload.get("origin") == _SELF_ORIGIN
