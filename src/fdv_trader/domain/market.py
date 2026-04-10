from __future__ import annotations

from dataclasses import dataclass, field, replace
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

    def with_trading_status(
        self,
        trading_status: TradingStatus,
        *,
        reject_reason: str | None = None,
    ) -> "Market":
        return replace(self, trading_status=trading_status, reject_reason=reject_reason)

    def with_tick_size(self, tick_size: Decimal) -> "Market":
        return replace(self, tick_size=tick_size)

    def with_min_order_size(self, min_order_size: Decimal) -> "Market":
        return replace(self, min_order_size=min_order_size)

    def with_metadata(
        self,
        *,
        event_id: str | None = None,
        event_title: str | None = None,
        event_slug: str | None = None,
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        matched_keywords: tuple[str, ...] | None = None,
        yes_token_id: str | None = None,
        no_token_id: str | None = None,
        neg_risk: bool | None = None,
    ) -> "Market":
        return replace(
            self,
            event_id=self.event_id if event_id is None else event_id,
            event_title=self.event_title if event_title is None else event_title,
            event_slug=self.event_slug if event_slug is None else event_slug,
            category=self.category if category is None else category,
            tags=self.tags if tags is None else tags,
            matched_keywords=(
                self.matched_keywords if matched_keywords is None else matched_keywords
            ),
            yes_token_id=self.yes_token_id if yes_token_id is None else yes_token_id,
            no_token_id=self.no_token_id if no_token_id is None else no_token_id,
            neg_risk=self.neg_risk if neg_risk is None else neg_risk,
        )
