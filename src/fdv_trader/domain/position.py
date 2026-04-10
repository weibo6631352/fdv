from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Position:
    condition_id: str
    token_id: str
    shares: Decimal
    cost_usdc: Decimal
    open_sell_shares: Decimal = Decimal("0")

