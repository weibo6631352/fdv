from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fdv_trader.domain.constants import ENTRY_NO_PRICE_MAX, EXIT_NO_PRICE


@dataclass(frozen=True, slots=True)
class CurrentStrategyConfig:
    entry_no_price_max: Decimal = ENTRY_NO_PRICE_MAX
    exit_no_price: Decimal = EXIT_NO_PRICE


__all__ = ["CurrentStrategyConfig"]
