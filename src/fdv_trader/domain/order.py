from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from datetime import datetime


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    FAK = "FAK"
    GTC = "GTC"


class OrderStatus(StrEnum):
    CREATED = "created"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    CANCEL_REQUESTED = "cancel_requested"
    MATCHED = "matched"
    PARTIALLY_FILLED = "partially_filled"
    NO_FILL = "no_fill"
    LIVE = "live"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Order:
    trace_id: str
    condition_id: str
    token_id: str
    side: OrderSide
    order_type: OrderType
    price: Decimal
    market_slug: str | None = None
    # BUY 订单的 amount_usdc 表示 USDC.e 花费金额；SELL 订单不要复用它表示 shares。
    amount_usdc: Decimal | None = None
    # SELL 订单的 size_shares 表示 outcome token 的 shares；BUY 订单保留空值，避免语义混淆。
    size_shares: Decimal | None = None
    notional_usdc: Decimal | None = None
    order_id: str | None = None
    trade_id: str | None = None
    status: OrderStatus = OrderStatus.CREATED
    idempotency_key: str | None = None
    reason: str = ""
    post_only: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


OrderIntent = Order
