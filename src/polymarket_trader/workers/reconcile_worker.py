from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from uuid import uuid4

from polymarket_trader.app.reconcile_service import (
    ReconcileAction,
    ReconcileActionType,
    ReconcilePlan,
    ReconcileService,
)
from polymarket_trader.app.trading_service import TradingService
from polymarket_trader.domain.events import DomainEvent, DomainEventType, Fill, OutboxPriority
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import (
    CancelOrderIntent,
    Order,
    OrderRecord,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    ReplaceOrderIntent,
    SellOrderIntent,
)
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.domain.position import Position
from polymarket_trader.infra.polymarket import ClobClient, DataClient, GammaClient, PolymarketTradingClient
from polymarket_trader.runtime.account_state import AccountSnapshot, AccountStateStore
from polymarket_trader.runtime.event_bus import EventBus
from polymarket_trader.runtime.registry import MarketRegistry, MarketRegistrySnapshot
from polymarket_trader.workers.market_ws_worker import MarketWsWorker

RegistrySnapshotProvider = Callable[[], MarketRegistrySnapshot]
AccountSnapshotProvider = Callable[[], AccountSnapshot]

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ReconcileWorkerResult:
    trace_id: str
    plan: ReconcilePlan
    applied_actions: tuple[ReconcileAction, ...]
    failed_actions: tuple[tuple[ReconcileAction, str], ...]


@dataclass(frozen=True, slots=True)
class AuthoritativeMarketRefresh:
    requested_market: Market
    refreshed_market: Market | None
    orderbook_snapshot: OrderbookSnapshot | None
    fee_rate_refreshed: bool = False
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoritativeRefreshSummary:
    trace_id: str
    market_count: int
    refreshed_markets: int
    refreshed_orderbooks: int
    refreshed_fee_rates: int
    refreshed_positions: int
    refreshed_open_orders: int
    refreshed_fills: int
    refreshed_balance: bool
    refreshed_allowance: bool
    user_refresh_enabled: bool
    failures: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "market_count": self.market_count,
            "refreshed_markets": self.refreshed_markets,
            "refreshed_orderbooks": self.refreshed_orderbooks,
            "refreshed_fee_rates": self.refreshed_fee_rates,
            "refreshed_positions": self.refreshed_positions,
            "refreshed_open_orders": self.refreshed_open_orders,
            "refreshed_fills": self.refreshed_fills,
            "refreshed_balance": self.refreshed_balance,
            "refreshed_allowance": self.refreshed_allowance,
            "user_refresh_enabled": self.user_refresh_enabled,
            "failures": list(self.failures),
        }


@dataclass(frozen=True, slots=True)
class ReconcileWorkerResultSummary:
    trace_id: str
    trigger_event_type: str | None
    started_at: datetime
    completed_at: datetime
    market_count: int
    diff_count: int
    action_count: int
    applied_action_count: int
    failed_action_count: int
    refresh_failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconcileWorkerStatus:
    running: bool
    last_trace_id: str | None
    last_trigger_event_type: str | None
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    last_refresh_summary: AuthoritativeRefreshSummary | None
    last_result: ReconcileWorkerResultSummary | None
    recent_results: tuple[ReconcileWorkerResultSummary, ...]


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
        registry: MarketRegistry | None = None,
        market_ws_worker: MarketWsWorker | None = None,
        gamma_client: GammaClient | None = None,
        clob_client: ClobClient | None = None,
        data_client: DataClient | None = None,
        trading_client: PolymarketTradingClient | None = None,
    ) -> None:
        self._event_bus = event_bus
        if reconcile_service is None:
            raise ValueError("reconcile_service is required")
        self._reconcile_service = reconcile_service
        self._registry_snapshot_provider = registry_snapshot_provider
        self._account_snapshot_provider = account_snapshot_provider
        self._account_state_store = account_state_store
        self._trading_service = trading_service
        self._executor = executor
        self._registry = registry
        self._market_ws_worker = market_ws_worker
        self._gamma_client = gamma_client
        self._clob_client = clob_client
        self._data_client = data_client
        self._trading_client = trading_client
        self._running = False
        self._last_trace_id: str | None = None
        self._last_trigger_event_type: str | None = None
        self._last_started_at: datetime | None = None
        self._last_completed_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error: str | None = None
        self._last_refresh_summary: AuthoritativeRefreshSummary | None = None
        self._last_result: ReconcileWorkerResultSummary | None = None
        self._recent_results: deque[ReconcileWorkerResultSummary] = deque(maxlen=8)

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
        started_at = _utc_now()
        self._running = True
        self._last_started_at = started_at
        self._last_trace_id = trace_id
        self._last_trigger_event_type = None if trigger is None else str(trigger.event_type)
        try:
            result = await self.reconcile_once(trace_id=trace_id, trigger_event=trigger)
        except Exception as exc:
            self._last_error = str(exc)
            self._last_completed_at = _utc_now()
            raise
        else:
            completed_at = _utc_now()
            self._last_completed_at = completed_at
            self._last_success_at = completed_at
            self._last_error = None
            summary = ReconcileWorkerResultSummary(
                trace_id=result.trace_id,
                trigger_event_type=self._last_trigger_event_type,
                started_at=started_at,
                completed_at=completed_at,
                market_count=len(result.plan.market_plans),
                diff_count=result.plan.diff_count,
                action_count=sum(len(plan.actions) for plan in result.plan.market_plans),
                applied_action_count=len(result.applied_actions),
                failed_action_count=len(result.failed_actions),
                refresh_failures=self._last_refresh_summary.failures
                if self._last_refresh_summary is not None
                else (),
            )
            self._last_result = summary
            self._recent_results.append(summary)
            return result
        finally:
            self._running = False

    def status_snapshot(self) -> ReconcileWorkerStatus:
        return ReconcileWorkerStatus(
            running=self._running,
            last_trace_id=self._last_trace_id,
            last_trigger_event_type=self._last_trigger_event_type,
            last_started_at=self._last_started_at,
            last_completed_at=self._last_completed_at,
            last_success_at=self._last_success_at,
            last_error=self._last_error,
            last_refresh_summary=self._last_refresh_summary,
            last_result=self._last_result,
            recent_results=tuple(self._recent_results),
        )

    async def reconcile_once(
        self,
        *,
        trace_id: str | None = None,
        trigger_event: DomainEvent | None = None,
        condition_ids: tuple[str, ...] | None = None,
    ) -> ReconcileWorkerResult:
        trace_id = trace_id or getattr(trigger_event, "trace_id", None) or uuid4().hex
        self._running = True
        self._last_started_at = _utc_now()
        self._last_trace_id = trace_id
        self._last_trigger_event_type = None if trigger_event is None else str(trigger_event.event_type)
        refresh_summary = await self._refresh_authoritative_state(
            trace_id=trace_id,
            condition_ids=condition_ids,
        )
        self._last_refresh_summary = refresh_summary
        if refresh_summary.failures:
            logger.warning(
                "reconcile authoritative refresh degraded",
                extra={
                    "trace_id": trace_id,
                    "failure_count": len(refresh_summary.failures),
                    "failures": refresh_summary.failures,
                },
            )
        registry_snapshot, account_snapshot = self._resolve_snapshots()
        plan = self._reconcile_service.build_reconcile_plan(
            registry_snapshot=registry_snapshot,
            account_snapshot=account_snapshot,
            trace_id=trace_id,
            condition_ids=condition_ids,
        )
        await self._publish(
            OutboxPriority.P3,
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
                    "refresh_summary": refresh_summary.as_payload(),
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
                    OutboxPriority.P3,
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
            self._prune_strategy_filtered_markets(self._account_state_store.snapshot())

        completed_at = _utc_now()
        self._last_completed_at = completed_at
        self._last_success_at = completed_at
        self._last_error = None

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
        if action.action_type == ReconcileActionType.REPLACE_OPEN_SELL:
            await self._apply_replace(action, market, account_snapshot)
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

    async def _apply_replace(
        self,
        action: ReconcileAction,
        market: Market,
        account_snapshot: AccountSnapshot,
    ) -> None:
        replace_intent = action.intent
        if not isinstance(replace_intent, ReplaceOrderIntent):
            raise TypeError("replace action is missing replace intent")

        result = None
        submitted = False
        if self._trading_service is not None:
            review = await self._trading_service.replace(replace_intent)
            result = review.order_result
            submitted = review.submitted and _submission_succeeded(result)
        if not submitted and self._executor is not None and hasattr(self._executor, "replace"):
            result = self._executor.replace(replace_intent)
            if hasattr(result, "__await__"):
                result = await result
            submitted = _submission_succeeded(result)

        if self._account_state_store is None or not submitted:
            return

        current_snapshot = self._account_state_store.snapshot()
        existing_order = _find_open_order(
            current_snapshot,
            action.condition_id,
            action.token_id,
            action.source_order_id,
        ) or _find_open_order(
            account_snapshot,
            action.condition_id,
            action.token_id,
            action.source_order_id,
        )
        existing_size = Decimal("0") if existing_order is None else _order_open_size(existing_order)
        if action.source_order_id is not None:
            self._account_state_store.remove_order(action.source_order_id)

        replacement_order_id = replace_intent.order_id
        replacement_remaining = replace_intent.size_shares
        replacement_price = replace_intent.new_price
        replacement_status = OrderStatus.SUBMITTED
        matched_shares = Decimal("0")
        trade_id = None
        if isinstance(result, OrderResult):
            replacement_order_id = result.order_id or replacement_order_id
            replacement_price = result.price or replacement_price
            matched_shares = result.matched_shares
            trade_id = result.trade_id
            replacement_status = _order_result_to_order_status(result)
            replacement_remaining = result.remaining_shares
            if result.status in {OrderResultStatus.LIVE, OrderResultStatus.PARTIAL_FILL} and replacement_remaining <= Decimal(
                "0"
            ):
                replacement_remaining = max(replace_intent.size_shares - result.matched_shares, Decimal("0"))
        if replacement_remaining < Decimal("0"):
            replacement_remaining = Decimal("0")

        if replacement_status in {
            OrderStatus.SUBMITTED,
            OrderStatus.LIVE,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CREATED,
            OrderStatus.SIGNED,
        }:
            self._account_state_store.upsert_order(
                OrderRecord(
                    trace_id=replace_intent.trace_id,
                    condition_id=replace_intent.condition_id,
                    token_id=replace_intent.token_id,
                    side=OrderSide.SELL,
                    order_type=OrderType.GTC,
                    price=replacement_price,
                    market_slug=replace_intent.market_slug,
                    size_shares=replace_intent.size_shares,
                    filled_shares=matched_shares,
                    remaining_shares=replacement_remaining,
                    notional_usdc=replacement_price * replace_intent.size_shares,
                    order_id=replacement_order_id,
                    trade_id=trade_id,
                    status=replacement_status,
                    idempotency_key=replace_intent.idempotency_key or replacement_order_id,
                    reason=replace_intent.reason or "reconcile_replace_sell",
                    created_at=_utc_now(),
                    updated_at=_utc_now(),
                )
            )
        else:
            self._account_state_store.remove_order(replacement_order_id)

        current_position = current_snapshot.get_position(action.condition_id, action.token_id)
        if current_position is None:
            current_position = account_snapshot.get_position(action.condition_id, action.token_id)
        if current_position is None:
            return
        updated_open_sell = max(current_position.open_sell_shares - existing_size, Decimal("0")) + replacement_remaining
        self._account_state_store.upsert_position(
            current_position.with_open_sell_shares(updated_open_sell)
        )

    async def _publish_diff(self, trace_id: str, market: Market, action: ReconcileAction) -> None:
        await self._publish(
            OutboxPriority.P3,
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

    def _prune_strategy_filtered_markets(self, account_snapshot: AccountSnapshot) -> None:
        if self._registry is None:
            return
        markets = self._registry.snapshot().markets
        for market in markets:
            if market.trading_status != TradingStatus.PAUSED:
                continue
            if market.reject_reason != "strategy_filtered_out":
                continue
            if _market_has_exposure(account_snapshot, market):
                continue
            self._registry.remove_market(market.condition_id)
            if self._market_ws_worker is not None and hasattr(self._market_ws_worker, "untrack_market"):
                self._market_ws_worker.untrack_market(market.no_token_id)

    def _resolve_snapshots(self) -> tuple[MarketRegistrySnapshot, AccountSnapshot]:
        if self._registry is not None:
            registry_snapshot = self._registry.snapshot()
        elif self._registry_snapshot_provider is not None:
            registry_snapshot = self._registry_snapshot_provider()
        else:
            registry_snapshot = MarketRegistrySnapshot(tuple())

        if self._account_state_store is not None:
            account_snapshot = self._account_state_store.snapshot()
        elif self._account_snapshot_provider is not None:
            account_snapshot = self._account_snapshot_provider()
        else:
            account_snapshot = AccountSnapshot()

        return registry_snapshot, account_snapshot

    async def _refresh_authoritative_state(
        self,
        *,
        trace_id: str,
        condition_ids: tuple[str, ...] | None = None,
    ) -> AuthoritativeRefreshSummary:
        markets = self._target_markets(condition_ids=condition_ids)
        if not markets:
            return AuthoritativeRefreshSummary(
                trace_id=trace_id,
                market_count=0,
                refreshed_markets=0,
                refreshed_orderbooks=0,
                refreshed_fee_rates=0,
                refreshed_positions=0,
                refreshed_open_orders=0,
                refreshed_fills=0,
                refreshed_balance=False,
                refreshed_allowance=False,
                user_refresh_enabled=self._trading_client is not None,
            )

        market_refreshes = await asyncio.gather(
            *(self._refresh_market_authority(market) for market in markets),
            return_exceptions=True,
        )
        refresh_failures: list[str] = []
        refreshed_markets = 0
        refreshed_orderbooks = 0
        refreshed_fee_rates = 0

        for item in market_refreshes:
            if isinstance(item, Exception):
                refresh_failures.append(str(item))
                continue
            if item.refreshed_market is not None:
                refreshed_markets += 1
                self._apply_refreshed_market(item.refreshed_market)
            if item.orderbook_snapshot is not None:
                refreshed_orderbooks += 1
                await self._apply_refreshed_orderbook(
                    item.refreshed_market or item.requested_market,
                    item.orderbook_snapshot,
                )
            if item.fee_rate_refreshed:
                refreshed_fee_rates += 1
            for failure in item.failures:
                refresh_failures.append(failure)

        account_summary = await self._refresh_account_authority(trace_id=trace_id, markets=markets)
        refresh_failures.extend(account_summary.failures)

        return AuthoritativeRefreshSummary(
            trace_id=trace_id,
            market_count=len(markets),
            refreshed_markets=refreshed_markets,
            refreshed_orderbooks=refreshed_orderbooks,
            refreshed_fee_rates=refreshed_fee_rates,
            refreshed_positions=account_summary.refreshed_positions,
            refreshed_open_orders=account_summary.refreshed_open_orders,
            refreshed_fills=account_summary.refreshed_fills,
            refreshed_balance=account_summary.refreshed_balance,
            refreshed_allowance=account_summary.refreshed_allowance,
            user_refresh_enabled=account_summary.user_refresh_enabled,
            failures=tuple(refresh_failures),
        )

    def _target_markets(self, *, condition_ids: tuple[str, ...] | None = None) -> tuple[Market, ...]:
        condition_id_filter = set(condition_ids or ())
        if self._registry_snapshot_provider is not None:
            markets = self._registry_snapshot_provider().markets
        elif self._registry is not None:
            markets = self._registry.snapshot().markets
        else:
            markets = tuple()
        if not condition_id_filter:
            return markets
        return tuple(market for market in markets if market.condition_id in condition_id_filter)

    async def _refresh_market_authority(self, market: Market) -> AuthoritativeMarketRefresh:
        failures: list[str] = []
        refreshed_market = await self._fetch_gamma_market(market, failures)
        market_for_orderbook = refreshed_market or market
        fee_rate_bps = None
        if (
            market_for_orderbook.fee_rate_bps is None
            and market_for_orderbook.taker_base_fee_bps is None
        ):
            fee_rate_bps = await self._fetch_fee_rate(market_for_orderbook, failures)
        fee_rate_refreshed = fee_rate_bps is not None
        if fee_rate_bps is not None:
            market_for_orderbook = market_for_orderbook.with_fee_rate(
                fee_rate_bps,
                fee_rate_updated_at=_utc_now(),
            )
            refreshed_market = market_for_orderbook
        orderbook_snapshot = await self._fetch_orderbook_snapshot(
            market_for_orderbook,
            failures,
        )
        return AuthoritativeMarketRefresh(
            requested_market=market,
            refreshed_market=refreshed_market,
            orderbook_snapshot=orderbook_snapshot,
            fee_rate_refreshed=fee_rate_refreshed,
            failures=tuple(failures),
        )

    async def _fetch_gamma_market(
        self,
        market: Market,
        failures: list[str],
    ) -> Market | None:
        if self._gamma_client is None:
            return None
        for slug in (market.market_slug, market.event_slug):
            if not slug:
                continue
            try:
                candidates = await self._gamma_client.list_markets(
                    slug=str(slug),
                    active=None,
                    closed=None,
                    limit=25,
                )
                gamma_market = _pick_gamma_market(candidates, market)
                if gamma_market is None:
                    failures.append(f"gamma:{market.condition_id}:{slug}:not_found")
                    continue
                refreshed_market = self._merge_gamma_market(
                    market,
                    gamma_market.to_market(),
                    gamma_market.clob_enabled,
                )
                return refreshed_market
            except Exception as exc:  # pragma: no cover - external SDK failure path
                failures.append(f"gamma:{market.condition_id}:{slug}:{exc}")
        return None

    async def _fetch_orderbook_snapshot(
        self,
        market: Market,
        failures: list[str],
    ) -> OrderbookSnapshot | None:
        if self._clob_client is None:
            return None
        try:
            orderbook = await self._clob_client.get_orderbook(
                market.no_token_id,
                market_slug=market.market_slug,
                condition_id=market.condition_id,
            )
            return orderbook.to_snapshot()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:{market.condition_id}:{market.no_token_id}:{exc}")
            return None

    async def _apply_refreshed_orderbook(self, market: Market, snapshot: OrderbookSnapshot) -> None:
        if self._market_ws_worker is None:
            return
        await self._market_ws_worker.apply_rest_snapshot(
            market.no_token_id,
            snapshot,
            source="reconcile_rest",
        )

    def _apply_refreshed_market(self, market: Market) -> None:
        if self._market_ws_worker is not None:
            self._market_ws_worker.track_market(market)
            return
        if self._registry is not None:
            self._registry.upsert(market)

    def _merge_gamma_market(
        self,
        current: Market,
        refreshed: Market,
        clob_enabled: bool | None,
    ) -> Market:
        merged = current.with_metadata(
            event_id=refreshed.event_id,
            event_title=refreshed.event_title,
            event_slug=refreshed.event_slug,
            icon_url=refreshed.icon_url,
            end_date=refreshed.end_date,
            category=refreshed.category,
            tags=refreshed.tags,
            matched_keywords=current.matched_keywords,
            yes_token_id=refreshed.yes_token_id,
            no_token_id=refreshed.no_token_id,
            neg_risk=refreshed.neg_risk,
        )
        merged = merged.with_tick_size(refreshed.tick_size)
        merged = merged.with_min_order_size(refreshed.min_order_size)
        merged = merged.with_fee_schedule(
            fees_enabled=refreshed.fees_enabled,
            maker_base_fee_bps=refreshed.maker_base_fee_bps,
            taker_base_fee_bps=refreshed.taker_base_fee_bps,
        )

        desired_status = refreshed.trading_status
        reject_reason = refreshed.reject_reason
        if clob_enabled is False and desired_status == TradingStatus.ELIGIBLE:
            desired_status = TradingStatus.PAUSED
            reject_reason = reject_reason or "orderbook_disabled"

        if current.trading_status in {
            TradingStatus.RESOLVED,
            TradingStatus.REJECTED,
        }:
            desired_status = current.trading_status
            reject_reason = current.reject_reason
        elif (
            current.trading_status == TradingStatus.PAUSED
            and current.reject_reason == "manual_pause"
            and desired_status == TradingStatus.ELIGIBLE
        ):
            desired_status = TradingStatus.PAUSED
            reject_reason = current.reject_reason

        return merged.with_trading_status(desired_status, reject_reason=reject_reason)

    async def _fetch_fee_rate(
        self,
        market: Market,
        failures: list[str],
    ) -> int | None:
        if self._clob_client is None:
            return None
        try:
            return await self._clob_client.get_fee_rate(market.no_token_id)
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:fee_rate:{market.condition_id}:{market.no_token_id}:{exc}")
            return None

    async def _refresh_account_authority(
        self,
        *,
        trace_id: str,
        markets: tuple[Market, ...],
    ) -> AuthoritativeRefreshSummary:
        failures: list[str] = []
        user_refresh_enabled = bool(
            self._trading_client is not None
            or (
                self._data_client is not None
                and self._clob_client is not None
                and self._data_client.has_auth_client
                and self._clob_client.has_auth_client
            )
        )
        if not user_refresh_enabled:
            return AuthoritativeRefreshSummary(
                trace_id=trace_id,
                market_count=len(markets),
                refreshed_markets=0,
                refreshed_orderbooks=0,
                refreshed_fee_rates=0,
                refreshed_positions=0,
                refreshed_open_orders=0,
                refreshed_fills=0,
                refreshed_balance=False,
                refreshed_allowance=False,
                user_refresh_enabled=False,
                failures=(),
            )

        positions_task = asyncio.create_task(self._fetch_positions(failures))
        open_orders_task = asyncio.create_task(self._fetch_open_orders(failures))
        fills_task = asyncio.create_task(self._fetch_fills(failures))
        balance_task = asyncio.create_task(self._fetch_balance(failures))
        positions, open_orders, fills, balance_result = await asyncio.gather(
            positions_task,
            open_orders_task,
            fills_task,
            balance_task,
        )
        balance, allowance, balance_refreshed, allowance_refreshed = balance_result

        if self._account_state_store is not None:
            if positions is not None:
                self._account_state_store.replace_positions(positions)
            if open_orders is not None:
                self._account_state_store.replace_open_orders(open_orders)
            if fills is not None:
                self._account_state_store.replace_fills(fills)
            if balance_refreshed or allowance_refreshed:
                self._account_state_store.update_balances(
                    balance_usdc=balance,
                    allowance_usdc=allowance,
                )

        return AuthoritativeRefreshSummary(
            trace_id=trace_id,
            market_count=len(markets),
            refreshed_markets=0,
            refreshed_orderbooks=0,
            refreshed_fee_rates=0,
            refreshed_positions=0 if positions is None else len(positions),
            refreshed_open_orders=0 if open_orders is None else len(open_orders),
            refreshed_fills=0 if fills is None else len(fills),
            refreshed_balance=balance_refreshed,
            refreshed_allowance=allowance_refreshed,
            user_refresh_enabled=True,
            failures=tuple(failures),
        )

    async def _fetch_positions(
        self,
        failures: list[str],
    ) -> tuple[Position, ...] | None:
        if self._data_client is None:
            return None
        try:
            positions = await self._data_client.list_positions()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"data:positions:{exc}")
            return None
        return tuple(position.to_position() for position in positions)

    async def _fetch_open_orders(
        self,
        failures: list[str],
    ) -> tuple[OrderRecord, ...] | None:
        if self._clob_client is None:
            return None
        try:
            orders = await self._clob_client.list_open_orders()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:open_orders:{exc}")
            return None
        return tuple(order.to_order_record() for order in orders)

    async def _fetch_fills(
        self,
        failures: list[str],
    ) -> tuple[Fill, ...] | None:
        if self._clob_client is None:
            return None
        try:
            fills = await self._clob_client.list_fills()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:fills:{exc}")
            return None
        return tuple(fill.to_fill() for fill in fills)

    async def _fetch_balance(
        self,
        failures: list[str],
    ) -> tuple[Decimal, Decimal, bool, bool]:
        if self._clob_client is None:
            return Decimal("0"), Decimal("0"), False, False
        try:
            balance = await self._clob_client.get_balance_allowance()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:balance_allowance:{exc}")
            return Decimal("0"), Decimal("0"), False, False
        return balance.balance_usdc, balance.allowance_usdc, True, True


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


def _market_has_exposure(account_snapshot: AccountSnapshot, market: Market) -> bool:
    position = account_snapshot.get_position(market.condition_id, market.no_token_id)
    if position is not None and (
        position.shares > 0
        or position.open_buy_shares > 0
        or position.open_sell_shares > 0
        or position.pending_buy_shares > 0
    ):
        return True
    return bool(account_snapshot.open_orders_for_market(market.condition_id, market.no_token_id))


def _order_open_size(order: Order) -> Decimal:
    if order.remaining_shares is not None:
        return max(order.remaining_shares, Decimal("0"))
    if order.size_shares is not None:
        return max(order.size_shares, Decimal("0"))
    if order.amount_usdc is not None:
        return max(order.amount_usdc, Decimal("0"))
    return Decimal("0")


def _order_result_to_order_status(result: OrderResult) -> OrderStatus:
    return {
        OrderResultStatus.FULL_FILL: OrderStatus.MATCHED,
        OrderResultStatus.PARTIAL_FILL: OrderStatus.PARTIALLY_FILLED,
        OrderResultStatus.NO_FILL: OrderStatus.NO_FILL,
        OrderResultStatus.LIVE: OrderStatus.LIVE,
        OrderResultStatus.REJECTED: OrderStatus.REJECTED,
        OrderResultStatus.FAILED: OrderStatus.FAILED,
        OrderResultStatus.CANCELLED: OrderStatus.CANCELLED,
        OrderResultStatus.UNKNOWN_TIMEOUT: OrderStatus.FAILED,
    }[result.status]


def _find_open_order(
    snapshot: AccountSnapshot | None,
    condition_id: str,
    token_id: str,
    order_id: str | None,
) -> Order | None:
    if snapshot is None or order_id is None:
        return None
    for order in snapshot.open_orders_for_market(condition_id, token_id):
        candidate_id = order.order_id or order.idempotency_key
        if candidate_id == order_id:
            return order
    return None


def _pick_gamma_market(
    candidates: tuple[object, ...],
    market: Market,
) -> object | None:
    for candidate in candidates:
        if getattr(candidate, "condition_id", None) == market.condition_id:
            return candidate
    for candidate in candidates:
        if getattr(candidate, "no_token_id", None) == market.no_token_id:
            return candidate
    for candidate in candidates:
        if getattr(candidate, "market_slug", None) == market.market_slug:
            return candidate
    return None
