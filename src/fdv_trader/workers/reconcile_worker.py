from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from uuid import uuid4

from fdv_trader.app.reconcile_service import (
    ReconcileAction,
    ReconcileActionType,
    ReconcilePlan,
    ReconcileService,
)
from fdv_trader.app.trading_service import TradingService
from fdv_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import (
    BuyOrderIntent,
    CancelOrderIntent,
    Order,
    OrderRecord,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    SellOrderIntent,
)
from fdv_trader.domain.position import Position
from fdv_trader.runtime.account_state import AccountSnapshot, AccountStateStore
from fdv_trader.runtime.event_bus import EventBus
from fdv_trader.runtime.registry import MarketRegistrySnapshot

RegistrySnapshotProvider = Callable[[], MarketRegistrySnapshot]
AccountSnapshotProvider = Callable[[], AccountSnapshot]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ReconcileWorkerResult:
    trace_id: str
    plan: ReconcilePlan
    applied_actions: tuple[ReconcileAction, ...]
    failed_actions: tuple[tuple[ReconcileAction, str], ...]


class ReconcileWorker:
    priority = "P2"

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        reconcile_service: ReconcileService | None = None,
        registry_snapshot_provider: RegistrySnapshotProvider | None = None,
        account_snapshot_provider: AccountSnapshotProvider | None = None,
        account_state_store: AccountStateStore | None = None,
        trading_service: TradingService | None = None,
        executor: object | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._reconcile_service = reconcile_service or ReconcileService()
        self._registry_snapshot_provider = registry_snapshot_provider
        self._account_snapshot_provider = account_snapshot_provider
        self._account_state_store = account_state_store
        self._trading_service = trading_service
        self._executor = executor

    async def run(self) -> None:
        if self._event_bus is None:
            raise RuntimeError("ReconcileWorker requires an EventBus to run")
        while True:
            await self.run_once()

    async def run_once(self) -> ReconcileWorkerResult:
        trigger = None
        if self._event_bus is not None:
            trigger = await self._event_bus.next_maintenance_event()
        trace_id = getattr(trigger, "trace_id", None) or uuid4().hex
        return await self.reconcile_once(trace_id=trace_id, trigger_event=trigger)

    async def reconcile_once(
        self,
        *,
        trace_id: str | None = None,
        trigger_event: DomainEvent | None = None,
        condition_ids: tuple[str, ...] | None = None,
    ) -> ReconcileWorkerResult:
        registry_snapshot, account_snapshot = self._resolve_snapshots()
        trace_id = trace_id or getattr(trigger_event, "trace_id", None) or uuid4().hex
        plan = self._reconcile_service.build_reconcile_plan(
            registry_snapshot=registry_snapshot,
            account_snapshot=account_snapshot,
            trace_id=trace_id,
            condition_ids=condition_ids,
        )
        await self._publish(
            OutboxPriority.P2,
            DomainEvent(
                trace_id=trace_id,
                event_type=DomainEventType.RECONCILE_STARTED,
                event_id=uuid4().hex,
                reason="reconcile_started",
                created_at=_utc_now(),
                payload={
                    "market_count": len(plan.market_plans),
                    "paused_markets": plan.paused_markets,
                    "diff_count": plan.diff_count,
                    "trigger_event_type": None if trigger_event is None else str(trigger_event.event_type),
                },
            ),
        )

        applied_actions: list[ReconcileAction] = []
        failed_actions: list[tuple[ReconcileAction, str]] = []
        working_snapshot = account_snapshot

        for market_plan in plan.market_plans:
            if market_plan.pause_trading:
                await self._publish(
                    OutboxPriority.P1,
                    DomainEvent(
                        trace_id=trace_id,
                        event_type=DomainEventType.TRADING_PAUSED_FOR_MARKET,
                        event_id=uuid4().hex,
                        market_slug=market_plan.market.market_slug,
                        condition_id=market_plan.market.condition_id,
                        token_id=market_plan.market.no_token_id,
                        reason=market_plan.pause_reason or "market_not_tradable",
                        created_at=_utc_now(),
                        payload={
                            "market_status": market_plan.market.trading_status.value,
                            "pause_reason": market_plan.pause_reason,
                        },
                    ),
                )
                if self._account_state_store is not None:
                    self._account_state_store.pause_market(
                        market_plan.market.condition_id,
                        reason=market_plan.pause_reason or "market_not_tradable",
                    )
                    working_snapshot = self._account_state_store.snapshot()

            for action in market_plan.actions:
                await self._publish_diff(trace_id, market_plan.market, action)
                try:
                    await self._apply_action(action, market_plan.market, working_snapshot)
                    applied_actions.append(action)
                    if self._account_state_store is not None:
                        working_snapshot = self._account_state_store.snapshot()
                except Exception as exc:  # pragma: no cover - injected adapters can fail
                    failed_actions.append((action, str(exc)))

            if market_plan.has_changes:
                await self._publish(
                    OutboxPriority.P2,
                    DomainEvent(
                        trace_id=trace_id,
                        event_type=DomainEventType.RECONCILE_APPLIED,
                        event_id=uuid4().hex,
                        market_slug=market_plan.market.market_slug,
                        condition_id=market_plan.market.condition_id,
                        token_id=market_plan.market.no_token_id,
                        reason="reconcile_applied",
                        created_at=_utc_now(),
                        payload={
                            "action_count": len(market_plan.actions),
                            "applied_count": sum(
                                1 for item in applied_actions if item.condition_id == market_plan.market.condition_id
                            ),
                            "failed_count": sum(
                                1 for item, _ in failed_actions if item.condition_id == market_plan.market.condition_id
                            ),
                        },
                    ),
                )

        if self._account_state_store is not None:
            self._account_state_store.mark_reconciled()

        return ReconcileWorkerResult(
            trace_id=trace_id,
            plan=plan,
            applied_actions=tuple(applied_actions),
            failed_actions=tuple(failed_actions),
        )

    async def _apply_action(
        self,
        action: ReconcileAction,
        market: Market,
        account_snapshot: AccountSnapshot,
    ) -> None:
        if action.action_type == ReconcileActionType.PAUSE_TRADING:
            return
        if action.action_type == ReconcileActionType.CANCEL_OPEN_BUY:
            await self._apply_cancel(action, account_snapshot)
            return
        if action.action_type == ReconcileActionType.CANCEL_EXCESS_SELL:
            await self._apply_cancel(action, account_snapshot)
            return
        if action.action_type == ReconcileActionType.SUBMIT_MISSING_SELL:
            await self._apply_sell(action, market, account_snapshot)
            return
        raise RuntimeError(f"unsupported reconcile action: {action.action_type}")

    async def _apply_cancel(self, action: ReconcileAction, account_snapshot: AccountSnapshot) -> None:
        cancel_intent = action.intent
        if not isinstance(cancel_intent, CancelOrderIntent):
            raise TypeError("cancel action is missing cancel intent")

        result = None
        executor = self._executor
        if executor is not None and hasattr(executor, "cancel"):
            result = executor.cancel(cancel_intent)
            if hasattr(result, "__await__"):
                await result

        if self._account_state_store is not None and action.source_order_id is not None:
            self._account_state_store.remove_order(action.source_order_id)
            position = account_snapshot.get_position(action.condition_id, action.token_id)
            if position is not None:
                if action.action_type == ReconcileActionType.CANCEL_OPEN_BUY:
                    updated_position = position.with_open_buy_shares(Decimal("0"))
                    updated_position = updated_position.with_pending_buy_shares(Decimal("0"))
                else:
                    remaining = max(
                        position.open_sell_shares - (action.target_size_shares or Decimal("0")),
                        Decimal("0"),
                    )
                    updated_position = position.with_open_sell_shares(remaining)
                self._account_state_store.upsert_position(updated_position)

        if result is not None and isinstance(result, OrderResult) and result.status == OrderResultStatus.CANCELLED:
            return

    async def _apply_sell(
        self,
        action: ReconcileAction,
        market: Market,
        account_snapshot: AccountSnapshot,
    ) -> None:
        sell_intent = action.intent
        if not isinstance(sell_intent, SellOrderIntent):
            raise TypeError("sell action is missing sell intent")

        submitted = False
        if self._trading_service is not None:
            review = await self._trading_service.review_intent(
                sell_intent,
                market=market,
                position=account_snapshot.get_position(action.condition_id, action.token_id),
                open_orders=account_snapshot.open_orders_for_market(action.condition_id, action.token_id),
                classification_passed=True,
                market_active=market.trading_status == TradingStatus.ELIGIBLE,
                market_open=market.trading_status == TradingStatus.ELIGIBLE,
                clob_enabled=True,
                resolved=market.trading_status == TradingStatus.RESOLVED,
                cancelled=False,
                archived=market.trading_status == TradingStatus.CLOSED,
                balance_usdc=account_snapshot.balance_usdc,
                allowance_usdc=account_snapshot.allowance_usdc,
                max_open_orders=None,
                min_order_size=market.min_order_size,
                min_liquidity_usdc=Decimal("0"),
                max_spread=None,
            )
            submitted = review.submitted
        if not submitted and self._executor is not None and hasattr(self._executor, "submit"):
            result = self._executor.submit(sell_intent)
            if hasattr(result, "__await__"):
                result = await result
            submitted = _submission_succeeded(result)

        if self._account_state_store is not None and submitted:
            order_id = sell_intent.idempotency_key or f"{sell_intent.trace_id}:{sell_intent.condition_id}:{sell_intent.token_id}:sell"
            open_sell_shares = account_snapshot.open_sell_shares_for_market(
                action.condition_id,
                action.token_id,
            )
            current_position = account_snapshot.get_position(action.condition_id, action.token_id)
            if current_position is None:
                current_position = Position(
                    condition_id=action.condition_id,
                    token_id=action.token_id,
                    shares=Decimal("0"),
                    cost_usdc=Decimal("0"),
                    market_slug=action.market_slug,
                    open_sell_shares=sell_intent.size_shares,
                    pending_buy_shares=Decimal("0"),
                )
            else:
                current_position = current_position.with_open_sell_shares(
                    open_sell_shares + sell_intent.size_shares,
                )
            self._account_state_store.upsert_order(
                OrderRecord(
                    trace_id=sell_intent.trace_id,
                    condition_id=sell_intent.condition_id,
                    token_id=sell_intent.token_id,
                    side=OrderSide.SELL,
                    order_type=OrderType.GTC,
                    price=sell_intent.price,
                    market_slug=sell_intent.market_slug,
                    size_shares=sell_intent.size_shares,
                    remaining_shares=sell_intent.size_shares,
                    notional_usdc=sell_intent.notional_usdc,
                    order_id=order_id,
                    status=OrderStatus.SUBMITTED,
                    idempotency_key=sell_intent.idempotency_key or order_id,
                    reason="reconcile_submit_sell",
                    post_only=sell_intent.post_only,
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
            )
            self._account_state_store.upsert_position(current_position)

    async def _publish_diff(self, trace_id: str, market: Market, action: ReconcileAction) -> None:
        await self._publish(
            OutboxPriority.P2,
            DomainEvent(
                trace_id=trace_id,
                event_type=DomainEventType.RECONCILE_DIFF_DETECTED,
                event_id=uuid4().hex,
                market_slug=market.market_slug,
                condition_id=market.condition_id,
                token_id=market.no_token_id,
                reason=action.reason,
                created_at=_utc_now(),
                payload={
                    "action_type": action.action_type.value,
                    "source_order_id": action.source_order_id,
                    "source_order_side": None if action.source_order_side is None else action.source_order_side.value,
                    "target_size_shares": None if action.target_size_shares is None else str(action.target_size_shares),
                    "target_notional_usdc": None if action.target_notional_usdc is None else str(action.target_notional_usdc),
                    "pause_reason": action.pause_reason,
                },
            ),
        )

    async def _publish(self, priority: OutboxPriority, event: DomainEvent) -> None:
        if self._event_bus is not None:
            await self._event_bus.publish(priority, event)

    def _resolve_snapshots(self) -> tuple[MarketRegistrySnapshot, AccountSnapshot]:
        if self._registry_snapshot_provider is not None:
            registry_snapshot = self._registry_snapshot_provider()
        elif self._account_state_store is not None:
            registry_snapshot = MarketRegistrySnapshot(tuple())
        else:
            registry_snapshot = MarketRegistrySnapshot(tuple())

        if self._account_snapshot_provider is not None:
            account_snapshot = self._account_snapshot_provider()
        elif self._account_state_store is not None:
            account_snapshot = self._account_state_store.snapshot()
        else:
            account_snapshot = AccountSnapshot()

        return registry_snapshot, account_snapshot


def _submission_succeeded(result: object | None) -> bool:
    if result is None:
        return True
    if isinstance(result, OrderResult):
        return result.status not in {
            OrderResultStatus.REJECTED,
            OrderResultStatus.FAILED,
            OrderResultStatus.UNKNOWN_TIMEOUT,
        }
    status = getattr(result, "status", None)
    if isinstance(status, OrderResultStatus):
        return status not in {
            OrderResultStatus.REJECTED,
            OrderResultStatus.FAILED,
            OrderResultStatus.UNKNOWN_TIMEOUT,
        }
    if isinstance(status, str):
        return status.lower() not in {"rejected", "failed", "unknown_timeout"}
    submitted = getattr(result, "submitted", None)
    if submitted is not None:
        return bool(submitted)
    return True
