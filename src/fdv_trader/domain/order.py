from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    FAK = "FAK"
    GTC = "GTC"


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    MATCHED = "matched"
    PARTIALLY_FILLED = "partially_filled"
    NO_FILL = "no_fill"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    trace_id: str
    condition_id: str
    token_id: str
    side: OrderSide
    order_type: OrderType
    price: Decimal
    amount_usdc: Decimal | None = None
    size_shares: Decimal | None = None
    market_slug: str | None = None

