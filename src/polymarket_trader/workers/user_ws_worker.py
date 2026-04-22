from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Iterable, Mapping
from uuid import uuid4

from polymarket_trader.domain.events import DomainEvent, DomainEventType, Fill, OutboxPriority
from polymarket_trader.domain.order import Order, OrderStatus
from polymarket_trader.domain.position import Position
from polymarket_trader.infra.polymarket import user_ws_adapter
from polymarket_trader.runtime.account_state import AccountSnapshot, AccountStateStore
from polymarket_trader.runtime.event_bus import EventBus

MessageSource = Callable[[], Awaitable[Mapping[str, Any] | DomainEvent | None]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_first = user_ws_adapter.first_value
_coalesce_decimal = user_ws_adapter.coalesce_decimal
_flatten_message = user_ws_adapter.flatten_message
_message_type = user_ws_adapter.message_type
_extract_condition_id = user_ws_adapter.extract_condition_id
_extract_token_id = user_ws_adapter.extract_token_id
_extract_market_slug = user_ws_adapter.extract_market_slug
_extract_trace_id = user_ws_adapter.extract_trace_id
_extract_event_id = user_ws_adapter.extract_event_id
_iter_order_snapshots = user_ws_adapter.iter_order_snapshots
_iter_position_snapshots = user_ws_adapter.iter_position_snapshots
_iter_fill_snapshots = user_ws_adapter.iter_fill_snapshots
_is_snapshot_message = user_ws_adapter.is_snapshot_message
_order_from_fill = user_ws_adapter.order_from_fill
_apply_fill_to_position = user_ws_adapter.apply_fill_to_position


def _order_id(order: Order) -> str:
    return order.order_id or order.idempotency_key or (
        f"{order.condition_id}:{order.token_id}:{order.side.value}:{order.order_type.value}"
    )


def _order_to_payload(order: Order) -> dict[str, Any]:
    return {
        "trace_id": order.trace_id,
        "condition_id": order.condition_id,
        "token_id": order.token_id,
        "market_slug": order.market_slug,
        "side": order.side.value,
        "order_type": order.order_type.value,
        "price": str(order.price),
        "amount_usdc": None if order.amount_usdc is None else str(order.amount_usdc),
        "size_shares": None if order.size_shares is None else str(order.size_shares),
        "notional_usdc": None if order.notional_usdc is None else str(order.notional_usdc),
        "order_id": order.order_id,
        "trade_id": order.trade_id,
        "status": order.status.value,
        "idempotency_key": order.idempotency_key,
        "reason": order.reason,
        "post_only": order.post_only,
    }


def _position_to_payload(position: Position) -> dict[str, Any]:
    return {
        "condition_id": position.condition_id,
        "token_id": position.token_id,
        "market_slug": position.market_slug,
        "shares": str(position.shares),
        "cost_usdc": str(position.cost_usdc),
        "open_buy_shares": str(position.open_buy_shares),
        "open_sell_shares": str(position.open_sell_shares),
        "pending_buy_shares": str(position.pending_buy_shares),
        "confirmed_shares": str(position.confirmed_shares),
        "last_order_id": position.last_order_id,
        "last_trade_id": position.last_trade_id,
        "confirmation_status": position.confirmation_status,
    }


def _fill_to_payload(fill: Fill) -> dict[str, Any]:
    return {
        "trace_id": fill.trace_id,
        "event_id": fill.event_id,
        "condition_id": fill.condition_id,
        "token_id": fill.token_id,
        "market_slug": fill.market_slug,
        "order_id": fill.order_id,
        "trade_id": fill.trade_id,
        "side": fill.side,
        "price": None if fill.price is None else str(fill.price),
        "size": None if fill.size is None else str(fill.size),
        "notional_usdc": None if fill.notional_usdc is None else str(fill.notional_usdc),
        "status": fill.status,
        "reason": fill.reason,
        "confirmed_at": None if fill.confirmed_at is None else fill.confirmed_at.isoformat(),
    }


def _snapshot_to_payload(snapshot: AccountSnapshot) -> dict[str, Any]:
    return {
        "balance_usdc": str(snapshot.balance_usdc),
        "allowance_usdc": str(snapshot.allowance_usdc),
        "user_ws_connected": snapshot.user_ws_connected,
        "allow_new_entries": snapshot.allow_new_entries,
        "paused_markets": snapshot.paused_markets,
        "pause_reasons": snapshot.pause_reasons,
        "last_reconcile_at": (
            None if snapshot.last_reconcile_at is None else snapshot.last_reconcile_at.isoformat()
        ),
        "positions": [_position_to_payload(position) for position in snapshot.positions],
        "open_orders": [_order_to_payload(order) for order in snapshot.open_orders],
        "fills": [_fill_to_payload(fill) for fill in snapshot.fills],
    }


@dataclass(frozen=True, slots=True)
class UserWsProcessResult:
    message_type: str
    events: tuple[DomainEvent, ...]
    snapshot: AccountSnapshot
    connected: bool

    @property
    def emitted(self) -> int:
        return len(self.events)


@dataclass(frozen=True, slots=True)
class UserWsResultSummary:
    trace_id: str
    message_type: str
    event_count: int
    connected: bool
    allow_new_entries: bool
    condition_id: str | None
    token_id: str | None
    market_slug: str | None
    reason: str
    balance_usdc: Decimal
    allowance_usdc: Decimal
    open_order_count: int
    position_count: int
    fill_count: int
    last_reconcile_at: datetime | None
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class UserWsSubscriptionStatus:
    condition_id: str
    subscribed_at: datetime
    last_message_at: datetime | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class UserWsWorkerStatus:
    connected: bool
    allow_new_entries: bool
    subscribed_condition_ids: tuple[str, ...]
    subscription_count: int
    last_message_at: datetime | None
    last_connected_at: datetime | None
    last_disconnected_at: datetime | None
    last_reconcile_at: datetime | None
    last_error: str | None
    last_result: UserWsResultSummary | None
    recent_results: tuple[UserWsResultSummary, ...]
    balance_usdc: Decimal
    allowance_usdc: Decimal
    open_order_count: int
    position_count: int
    fill_count: int
    paused_market_count: int
    subscriptions: tuple[UserWsSubscriptionStatus, ...]


class UserWsWorker:
    priority = "P0"

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        account_state_store: AccountStateStore | None = None,
        message_source: MessageSource | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._account_state = account_state_store or AccountStateStore()
        self._message_source = message_source
        self._subscribed_condition_ids: dict[str, datetime] = {}
        self._last_message_at: datetime | None = None
        self._last_connected_at: datetime | None = None
        self._last_disconnected_at: datetime | None = None
        self._last_error: str | None = None
        self._last_result: UserWsResultSummary | None = None
        self._recent_results: deque[UserWsResultSummary] = deque(maxlen=8)

    def snapshot(self) -> AccountSnapshot:
        return self._account_state.snapshot()

    def status_snapshot(self) -> UserWsWorkerStatus:
        account_snapshot = self._account_state.snapshot()
        subscribed_condition_ids = tuple(sorted(self._subscribed_condition_ids))
        subscriptions = tuple(
            UserWsSubscriptionStatus(
                condition_id=condition_id,
                subscribed_at=self._subscribed_condition_ids[condition_id],
                last_message_at=self._last_message_at,
                last_error=self._last_error,
            )
            for condition_id in subscribed_condition_ids
        )
        return UserWsWorkerStatus(
            connected=account_snapshot.user_ws_connected,
            allow_new_entries=account_snapshot.allow_new_entries,
            subscribed_condition_ids=subscribed_condition_ids,
            subscription_count=len(subscribed_condition_ids),
            last_message_at=self._last_message_at,
            last_connected_at=self._last_connected_at,
            last_disconnected_at=self._last_disconnected_at,
            last_reconcile_at=account_snapshot.last_reconcile_at,
            last_error=self._last_error,
            last_result=self._last_result,
            recent_results=tuple(self._recent_results),
            balance_usdc=account_snapshot.balance_usdc,
            allowance_usdc=account_snapshot.allowance_usdc,
            open_order_count=len(account_snapshot.open_orders),
            position_count=len(account_snapshot.positions),
            fill_count=len(account_snapshot.fills),
            paused_market_count=len(account_snapshot.paused_markets),
            subscriptions=subscriptions,
        )

    def build_subscription_request(
        self,
        condition_ids: str | Iterable[str],
        *,
        auth: Mapping[str, str],
    ) -> dict[str, Any]:
        # User Channel 按官方当前 markets=condition_ids 订阅。
        normalized = (
            (condition_ids.strip(),)
            if isinstance(condition_ids, str) and condition_ids.strip()
            else tuple(
                str(condition_id).strip()
                for condition_id in condition_ids
                if str(condition_id).strip()
            )
        )
        subscribed_at = _utc_now()
        for condition_id in normalized:
            self._subscribed_condition_ids[condition_id] = subscribed_at
        return {
            "auth": {str(key): str(value) for key, value in auth.items()},
            "markets": list(normalized),
            "type": "user",
        }

    def record_error(self, reason: str) -> None:
        self._last_error = reason

    async def run(self) -> None:
        if self._message_source is None:
            raise RuntimeError("UserWsWorker requires a message_source to run")
        while True:
            message = await self._message_source()
            if message is None:
                continue
            await self.process_message(message)

    async def run_once(self) -> UserWsProcessResult | None:
        if self._message_source is None:
            raise RuntimeError("UserWsWorker requires a message_source to run")
        message = await self._message_source()
        if message is None:
            return None
        return await self.process_message(message)

    async def process_message(
        self,
        message: Mapping[str, Any] | DomainEvent,
    ) -> UserWsProcessResult:
        self._last_message_at = _utc_now()
        self._last_error = None
        payload = _flatten_message(message)
        message_type = _message_type(payload)
        trace_id = _extract_trace_id(payload)
        event_id = _extract_event_id(payload)

        if message_type in {"connected", "reconnected", "connection_open", "ws_connected"}:
            snapshot = self._account_state.mark_user_ws_connected(True)
            self._record_connection_state(True)
            return await self._emit_result(
                trace_id=trace_id,
                message_type=message_type,
                snapshot=snapshot,
                events=(),
                reason="connected",
                connected=True,
            )

        if message_type in {"disconnected", "disconnect", "connection_closed", "ws_disconnected"}:
            snapshot = self._account_state.mark_user_ws_connected(False)
            self._record_connection_state(False)
            return await self._emit_result(
                trace_id=trace_id,
                message_type=message_type,
                snapshot=snapshot,
                events=(),
                reason="disconnected",
                connected=False,
            )

        events: list[DomainEvent] = []

        if self._has_balance_fields(payload) or message_type == "balance":
            events.extend(
                await self._handle_balance(payload, trace_id=trace_id, event_id=event_id)
            )

        if self._has_position_fields(payload) or message_type in {"position", "positions"}:
            events.extend(
                await self._handle_position(
                    payload,
                    trace_id=trace_id,
                    event_id=event_id,
                )
            )

        if self._has_order_fields(payload) or message_type in {"order", "orders"}:
            events.extend(
                await self._handle_order(
                    payload,
                    trace_id=trace_id,
                    event_id=event_id,
                )
            )

        if self._has_fill_fields(payload) or message_type in {"trade", "fill", "fills"}:
            events.extend(
                await self._handle_fill(
                    payload,
                    trace_id=trace_id,
                    event_id=event_id,
                )
            )

        snapshot = self._account_state.snapshot()
        return await self._emit_result(
            trace_id=trace_id,
            message_type=message_type or "snapshot",
            snapshot=snapshot,
            events=tuple(events),
            reason="message_processed",
        )

    async def set_connection_state(
        self,
        connected: bool,
        *,
        trace_id: str | None = None,
        reason: str | None = None,
    ) -> UserWsProcessResult:
        trace_id = trace_id or uuid4().hex
        self._last_message_at = _utc_now()
        if connected:
            self._last_error = None
        if connected:
            snapshot = self._account_state.mark_user_ws_connected(True)
        else:
            snapshot = self._account_state.mark_user_ws_connected(False)
        self._record_connection_state(connected)
        return await self._emit_result(
            trace_id=trace_id,
            message_type="connection_state",
            snapshot=snapshot,
            events=(),
            reason=reason or "connection_state",
            connected=connected,
        )

    async def _handle_balance(
        self,
        payload: Mapping[str, Any],
        *,
        trace_id: str,
        event_id: str,
    ) -> list[DomainEvent]:
        snapshot_before = self._account_state.snapshot()
        balance_usdc = _coalesce_decimal(
            _first(payload, "balance_usdc", "available_balance_usdc", "usdc_balance", "balance"),
            _first(payload, "available_usdc", "available_balance", "available"),
            default=snapshot_before.balance_usdc,
        )
        allowance_usdc = _coalesce_decimal(
            _first(payload, "allowance_usdc", "allowance"),
            _first(payload, "approved_usdc", "approval_usdc"),
            default=snapshot_before.allowance_usdc,
        )
        snapshot = self._account_state.update_balances(
            balance_usdc=balance_usdc,
            allowance_usdc=allowance_usdc,
        )
        return [
            self._build_event(
                DomainEventType.BALANCE_UPDATED,
                trace_id=trace_id,
                event_id=uuid4().hex,
                condition_id=_extract_condition_id(payload),
                token_id=_extract_token_id(payload),
                market_slug=_extract_market_slug(payload),
                reason="balance_update",
                payload={
                    "balance_usdc": str(snapshot.balance_usdc),
                    "allowance_usdc": str(snapshot.allowance_usdc),
                    "user_ws_connected": snapshot.user_ws_connected,
                    "allow_new_entries": snapshot.allow_new_entries,
                    "paused_markets": list(snapshot.paused_markets),
                    "pause_reasons": [list(item) for item in snapshot.pause_reasons],
                    "last_reconcile_at": (
                        None
                        if snapshot.last_reconcile_at is None
                        else snapshot.last_reconcile_at.isoformat()
                    ),
                },
            )
        ]

    async def _handle_position(
        self,
        payload: Mapping[str, Any],
        *,
        trace_id: str,
        event_id: str,
    ) -> list[DomainEvent]:
        positions = tuple(_iter_position_snapshots(payload))
        if not positions:
            return []
        if _is_snapshot_message(payload):
            snapshot = self._account_state.replace_positions(positions)
        else:
            snapshot = self._account_state.snapshot()
            for position in positions:
                snapshot = self._account_state.upsert_position(position)
        return [
            self._build_event(
                DomainEventType.POSITION_UPDATED,
                trace_id=trace_id,
                event_id=uuid4().hex,
                condition_id=_extract_condition_id(payload),
                token_id=_extract_token_id(payload),
                market_slug=_extract_market_slug(payload),
                reason="position_update",
                payload={
                    "positions": [_position_to_payload(position) for position in positions],
                    "position_count": len(positions),
                    "snapshot": _snapshot_to_payload(snapshot),
                },
            )
        ]

    async def _handle_order(
        self,
        payload: Mapping[str, Any],
        *,
        trace_id: str,
        event_id: str,
    ) -> list[DomainEvent]:
        orders = tuple(_iter_order_snapshots(payload))
        if not orders:
            return []
        snapshot = self._account_state.snapshot()
        emitted: list[DomainEvent] = []
        for order in orders:
            if order.status in {
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.FAILED,
                OrderStatus.NO_FILL,
            }:
                snapshot = self._account_state.remove_order(_order_id(order))
            else:
                snapshot = self._account_state.upsert_order(order)
            emitted.append(
                self._build_event(
                    DomainEventType.ORDER_STATE_UPDATED,
                    trace_id=trace_id,
                    event_id=uuid4().hex,
                    condition_id=order.condition_id,
                    token_id=order.token_id,
                    market_slug=order.market_slug,
                    reason=order.reason or "order_update",
                    payload={
                        "order": _order_to_payload(order),
                        "open_orders": [
                            _order_to_payload(open_order)
                            for open_order in snapshot.open_orders_for_market(
                                order.condition_id,
                                order.token_id,
                            )
                        ],
                        "snapshot": _snapshot_to_payload(snapshot),
                    },
                )
            )
        return emitted

    async def _handle_fill(
        self,
        payload: Mapping[str, Any],
        *,
        trace_id: str,
        event_id: str,
    ) -> list[DomainEvent]:
        fills = tuple(_iter_fill_snapshots(payload))
        if not fills:
            return []

        snapshot = self._account_state.snapshot()
        emitted: list[DomainEvent] = []
        for fill in fills:
            snapshot = self._account_state.record_fill(fill)
            position = _apply_fill_to_position(snapshot.get_position(fill.condition_id or "", fill.token_id or ""), fill)
            if position is not None:
                snapshot = self._account_state.upsert_position(position)
            if fill.order_id is not None:
                order = _order_from_fill(fill)
                if order.status in {
                    OrderStatus.CANCELLED,
                    OrderStatus.REJECTED,
                    OrderStatus.FAILED,
                    OrderStatus.NO_FILL,
                }:
                    snapshot = self._account_state.remove_order(_order_id(order))
                else:
                    snapshot = self._account_state.upsert_order(order)
                emitted.append(
                    self._build_event(
                        DomainEventType.ORDER_STATE_UPDATED,
                        trace_id=trace_id,
                        event_id=uuid4().hex,
                        condition_id=fill.condition_id,
                        token_id=fill.token_id,
                        market_slug=fill.market_slug,
                        reason=fill.reason or "trade_update",
                        payload={
                            "order": _order_to_payload(order),
                            "fill": _fill_to_payload(fill),
                            "snapshot": _snapshot_to_payload(snapshot),
                        },
                    )
                )

            emitted.append(
                self._build_event(
                    DomainEventType.FILL_RECORDED,
                    trace_id=trace_id,
                    event_id=uuid4().hex,
                    condition_id=fill.condition_id,
                    token_id=fill.token_id,
                    market_slug=fill.market_slug,
                    reason=fill.reason or fill.status,
                    payload={
                        "fill": _fill_to_payload(fill),
                        "position": None if position is None else _position_to_payload(position),
                        "snapshot": _snapshot_to_payload(snapshot),
                    },
                )
            )
            if position is not None:
                emitted.append(
                    self._build_event(
                        DomainEventType.POSITION_UPDATED,
                        trace_id=trace_id,
                        event_id=uuid4().hex,
                        condition_id=fill.condition_id,
                        token_id=fill.token_id,
                        market_slug=fill.market_slug,
                        reason=fill.reason or "position_after_fill",
                        payload={
                            "position": _position_to_payload(position),
                            "fill": _fill_to_payload(fill),
                            "snapshot": _snapshot_to_payload(snapshot),
                        },
                    )
                )
        return emitted

    async def _emit_result(
        self,
        *,
        trace_id: str,
        message_type: str,
        snapshot: AccountSnapshot,
        events: tuple[DomainEvent, ...],
        reason: str = "",
        connected: bool | None = None,
    ) -> UserWsProcessResult:
        if self._event_bus is not None:
            for event in events:
                await self._event_bus.publish(OutboxPriority.P0, event)
        result = UserWsProcessResult(
            message_type=message_type,
            events=events,
            snapshot=snapshot,
            connected=snapshot.user_ws_connected if connected is None else connected,
        )
        summary = UserWsResultSummary(
            trace_id=trace_id,
            message_type=message_type,
            event_count=len(events),
            connected=result.connected,
            allow_new_entries=snapshot.allow_new_entries,
            condition_id=events[0].condition_id if events else None,
            token_id=events[0].token_id if events else None,
            market_slug=events[0].market_slug if events else None,
            reason=reason,
            balance_usdc=snapshot.balance_usdc,
            allowance_usdc=snapshot.allowance_usdc,
            open_order_count=len(snapshot.open_orders),
            position_count=len(snapshot.positions),
            fill_count=len(snapshot.fills),
            last_reconcile_at=snapshot.last_reconcile_at,
        )
        self._last_result = summary
        self._recent_results.append(summary)
        return result

    def _record_connection_state(self, connected: bool) -> None:
        now = _utc_now()
        if connected:
            self._last_connected_at = now
        else:
            self._last_disconnected_at = now

    def _build_event(
        self,
        event_type: DomainEventType,
        *,
        trace_id: str,
        event_id: str,
        condition_id: str | None = None,
        token_id: str | None = None,
        market_slug: str | None = None,
        reason: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> DomainEvent:
        return DomainEvent(
            trace_id=trace_id,
            event_type=event_type,
            event_id=event_id,
            condition_id=condition_id,
            token_id=token_id,
            market_slug=market_slug,
            reason=reason,
            created_at=_utc_now(),
            payload=dict(payload or {}),
        )

    def _has_balance_fields(self, payload: Mapping[str, Any]) -> bool:
        return any(
            key in payload
            for key in (
                "balance_usdc",
                "available_balance_usdc",
                "usdc_balance",
                "balance",
                "allowance_usdc",
                "allowance",
            )
        )

    def _has_position_fields(self, payload: Mapping[str, Any]) -> bool:
        return any(key in payload for key in ("position", "positions", "holdings"))

    def _has_order_fields(self, payload: Mapping[str, Any]) -> bool:
        return any(key in payload for key in ("order", "orders", "open_orders"))

    def _has_fill_fields(self, payload: Mapping[str, Any]) -> bool:
        return any(key in payload for key in ("trade", "trades", "fill", "fills"))
