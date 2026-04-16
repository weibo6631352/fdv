from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock

from polymarket_trader.domain.events import Fill
from polymarket_trader.domain.order import Order, OrderSide
from polymarket_trader.domain.position import Position


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    balance_usdc: Decimal = Decimal("0")
    allowance_usdc: Decimal = Decimal("0")
    positions: tuple[Position, ...] = ()
    open_orders: tuple[Order, ...] = ()
    fills: tuple[Fill, ...] = ()
    user_ws_connected: bool = False
    allow_new_entries: bool = False
    paused_markets: tuple[str, ...] = ()
    pause_reasons: tuple[tuple[str, str], ...] = ()
    last_reconcile_at: datetime | None = None

    def get_position(self, condition_id: str, token_id: str) -> Position | None:
        for position in self.positions:
            if position.condition_id == condition_id and position.token_id == token_id:
                return position
        return None

    def is_market_paused(self, condition_id: str) -> bool:
        return condition_id in self.paused_markets

    def open_orders_for_market(self, condition_id: str, token_id: str) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self.open_orders
            if order.condition_id == condition_id and order.token_id == token_id
        )

    def open_buy_orders_for_market(self, condition_id: str, token_id: str) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self.open_orders_for_market(condition_id, token_id)
            if order.side == OrderSide.BUY and order.open
        )

    def open_sell_orders_for_market(self, condition_id: str, token_id: str) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self.open_orders_for_market(condition_id, token_id)
            if order.side == OrderSide.SELL and order.open
        )

    def open_sell_shares_for_market(self, condition_id: str, token_id: str) -> Decimal:
        total = Decimal("0")
        for order in self.open_sell_orders_for_market(condition_id, token_id):
            if order.remaining_shares is not None:
                total += order.remaining_shares
            elif order.size_shares is not None:
                total += order.size_shares
        return total


class AccountStateStore:
    """Maintains copy-on-write account snapshots for P0 readers."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._positions: dict[tuple[str, str], Position] = {}
        self._open_orders: dict[str, Order] = {}
        self._fills: dict[str, Fill] = {}
        self._balance_usdc = Decimal("0")
        self._allowance_usdc = Decimal("0")
        self._user_ws_connected = False
        self._allow_new_entries = False
        self._paused_markets: dict[str, str] = {}
        self._last_reconcile_at: datetime | None = None
        self._snapshot = AccountSnapshot()

    def snapshot(self) -> AccountSnapshot:
        return self._snapshot

    def update_balances(
        self,
        *,
        balance_usdc: Decimal | None = None,
        allowance_usdc: Decimal | None = None,
    ) -> AccountSnapshot:
        with self._lock:
            if balance_usdc is not None:
                self._balance_usdc = balance_usdc
            if allowance_usdc is not None:
                self._allowance_usdc = allowance_usdc
            return self._publish_snapshot_locked()

    def upsert_position(self, position: Position) -> AccountSnapshot:
        with self._lock:
            self._positions[(position.condition_id, position.token_id)] = position
            return self._publish_snapshot_locked()

    def replace_positions(self, positions: tuple[Position, ...]) -> AccountSnapshot:
        with self._lock:
            self._positions = {
                (position.condition_id, position.token_id): position
                for position in positions
            }
            return self._publish_snapshot_locked()

    def upsert_order(self, order: Order) -> AccountSnapshot:
        with self._lock:
            order_id = order.order_id or order.idempotency_key or (
                f"{order.condition_id}:{order.token_id}:{order.side.value}:{order.status.value}"
            )
            self._open_orders[order_id] = order
            return self._publish_snapshot_locked()

    def remove_order(self, order_id: str) -> AccountSnapshot:
        with self._lock:
            self._open_orders.pop(order_id, None)
            return self._publish_snapshot_locked()

    def replace_open_orders(self, orders: tuple[Order, ...]) -> AccountSnapshot:
        with self._lock:
            self._open_orders = {}
            for order in orders:
                order_id = order.order_id or order.idempotency_key or (
                    f"{order.condition_id}:{order.token_id}:{order.side.value}:{order.status.value}"
                )
                self._open_orders[order_id] = order
            return self._publish_snapshot_locked()

    def record_fill(self, fill: Fill) -> AccountSnapshot:
        with self._lock:
            self._fills[fill.event_id] = fill
            return self._publish_snapshot_locked()

    def replace_fills(self, fills: tuple[Fill, ...]) -> AccountSnapshot:
        with self._lock:
            self._fills = {fill.event_id: fill for fill in fills}
            return self._publish_snapshot_locked()

    def mark_user_ws_connected(self, connected: bool) -> AccountSnapshot:
        with self._lock:
            self._user_ws_connected = connected
            if not connected:
                self._last_reconcile_at = None
                self._allow_new_entries = False
            return self._publish_snapshot_locked()

    def set_allow_new_entries(self, allowed: bool) -> AccountSnapshot:
        with self._lock:
            self._allow_new_entries = allowed and self._entry_gate_can_open_locked()
            return self._publish_snapshot_locked()

    def pause_market(self, condition_id: str, *, reason: str) -> AccountSnapshot:
        with self._lock:
            self._paused_markets[condition_id] = reason
            return self._publish_snapshot_locked()

    def resume_market(self, condition_id: str) -> AccountSnapshot:
        with self._lock:
            self._paused_markets.pop(condition_id, None)
            return self._publish_snapshot_locked()

    def mark_reconciled(self, reconciled_at: datetime | None = None) -> AccountSnapshot:
        with self._lock:
            self._last_reconcile_at = reconciled_at or _utc_now()
            self._allow_new_entries = self._entry_gate_can_open_locked()
            return self._publish_snapshot_locked()

    def _entry_gate_can_open_locked(self) -> bool:
        return self._user_ws_connected and self._last_reconcile_at is not None

    def _publish_snapshot_locked(self) -> AccountSnapshot:
        snapshot = AccountSnapshot(
            balance_usdc=self._balance_usdc,
            allowance_usdc=self._allowance_usdc,
            positions=tuple(self._positions.values()),
            open_orders=tuple(self._open_orders.values()),
            fills=tuple(self._fills.values()),
            user_ws_connected=self._user_ws_connected,
            allow_new_entries=self._allow_new_entries,
            paused_markets=tuple(self._paused_markets.keys()),
            pause_reasons=tuple(self._paused_markets.items()),
            last_reconcile_at=self._last_reconcile_at,
        )
        self._snapshot = snapshot
        return snapshot
