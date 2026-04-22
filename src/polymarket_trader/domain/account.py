from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from polymarket_trader.domain.events import Fill
from polymarket_trader.domain.order import Order, OrderSide
from polymarket_trader.domain.position import Position


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
