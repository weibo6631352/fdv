from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class StrategyRuntimeProfile:
    entry_no_price_max: Decimal = Decimal("0.60")
    min_liquidity_usdc: Decimal = Decimal("0")
    max_spread: Decimal | None = None
