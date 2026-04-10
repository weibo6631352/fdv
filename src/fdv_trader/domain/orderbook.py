from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True, slots=True)
class OrderbookSnapshot:
    token_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    received_at: datetime

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

