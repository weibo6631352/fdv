from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Position:
    condition_id: str
    token_id: str
    shares: Decimal
    cost_usdc: Decimal
    market_slug: str | None = None
    open_sell_shares: Decimal = Decimal("0")
    pending_buy_shares: Decimal = Decimal("0")
    updated_at: datetime | None = None
