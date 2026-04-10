from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class RawMarketEvent:
    source: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ClobOrderRequest:
    token_id: str
    side: str
    order_type: str
    price: Decimal
    amount: Decimal
    post_only: bool = False

