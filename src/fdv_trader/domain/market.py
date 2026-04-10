from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class TradingStatus(StrEnum):
    CANDIDATE = "candidate"
    ELIGIBLE = "eligible"
    PAUSED = "paused"
    CLOSED = "closed"
    RESOLVED = "resolved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Market:
    condition_id: str
    market_slug: str
    no_token_id: str
    yes_token_id: str | None = None
    event_id: str | None = None
    event_title: str | None = None
    event_slug: str | None = None
    tick_size: Decimal = Decimal("0.01")
    min_order_size: Decimal = Decimal("1")
    neg_risk: bool = False
    category: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    trading_status: TradingStatus = TradingStatus.CANDIDATE
    reject_reason: str | None = None

