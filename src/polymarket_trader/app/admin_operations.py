from __future__ import annotations

from decimal import Decimal
from typing import Sequence

from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import Order, OrderResult, OrderResultStatus, OrderStatus


def market_status_allowed_for_manual_order(market: Market) -> bool:
    return market.trading_status not in {
        TradingStatus.CLOSED,
        TradingStatus.RESOLVED,
        TradingStatus.REJECTED,
    }


def order_result_to_order_status(result: OrderResult) -> OrderStatus:
    mapping = {
        OrderResultStatus.FULL_FILL: OrderStatus.MATCHED,
        OrderResultStatus.PARTIAL_FILL: OrderStatus.PARTIALLY_FILLED,
        OrderResultStatus.NO_FILL: OrderStatus.NO_FILL,
        OrderResultStatus.LIVE: OrderStatus.LIVE,
        OrderResultStatus.REJECTED: OrderStatus.REJECTED,
        OrderResultStatus.FAILED: OrderStatus.FAILED,
        OrderResultStatus.CANCELLED: OrderStatus.CANCELLED,
        OrderResultStatus.UNKNOWN_TIMEOUT: OrderStatus.FAILED,
    }
    return mapping.get(result.status, OrderStatus.FAILED)


def normalize_order_id(order: Order) -> str:
    return order.order_id or order.idempotency_key or (
        f"{order.condition_id}:{order.token_id}:{order.side.value}:{order.status.value}"
    )


def order_open_shares(order: Order) -> Decimal | None:
    if order.remaining_shares is not None:
        return max(order.remaining_shares, Decimal("0"))
    if order.size_shares is not None:
        return max(order.size_shares, Decimal("0"))
    return None


def normalize_condition_ids(condition_ids: Sequence[str] | None) -> tuple[str, ...]:
    if not condition_ids:
        return ()
    return tuple(condition_id for condition_id in condition_ids if condition_id)


def order_status_to_text(status: OrderResultStatus) -> str:
    return {
        OrderResultStatus.FULL_FILL: "full_fill",
        OrderResultStatus.PARTIAL_FILL: "partial_fill",
        OrderResultStatus.NO_FILL: "no_fill",
        OrderResultStatus.LIVE: "live",
        OrderResultStatus.REJECTED: "rejected",
        OrderResultStatus.FAILED: "failed",
        OrderResultStatus.CANCELLED: "cancelled",
        OrderResultStatus.UNKNOWN_TIMEOUT: "unknown_timeout",
    }.get(status, "unknown")
