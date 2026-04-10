from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from fdv_trader.domain.classifier import ClassificationResult, MarketClassifier
from fdv_trader.domain.events import DomainEvent, DomainEventType
from fdv_trader.domain.market import Market
from fdv_trader.observability.trace import ensure_trace_id
from fdv_trader.runtime.registry import MarketRegistry


class MarketService:
    """Coordinates market discovery, classification, and registry updates."""

    def __init__(
        self,
        *,
        classifier: MarketClassifier | None = None,
        registry: MarketRegistry | None = None,
        market_tracker: Any | None = None,
    ) -> None:
        self._classifier = classifier or MarketClassifier()
        self._registry = registry
        self._market_tracker = market_tracker

    def ingest_raw_market(
        self,
        raw_market: Mapping[str, Any],
        *,
        source: str,
        trace_id: str | None = None,
        discovered_at: datetime | None = None,
    ) -> "MarketDiscoveryOutcome":
        trace_id = trace_id or ensure_trace_id()
        discovered_at = discovered_at or datetime.now(timezone.utc)
        classification = self._classifier.classify(raw_market)
        existing_market = self._lookup_existing_market(classification)

        market: Market | None = None
        subscription_request: dict[str, Any] | None = None
        if classification.accepted:
            market = classification.to_market()
            if self._registry is not None:
                self._registry.upsert(market)
            if self._market_tracker is not None:
                self._market_tracker.track_market(market)
                if hasattr(self._market_tracker, "build_subscription_request"):
                    subscription_request = self._market_tracker.build_subscription_request(
                        market.no_token_id
                    )

        discovery_kind = "market_updated" if existing_market is not None else "market_discovered"
        event = self._build_event(
            classification,
            trace_id=trace_id,
            source=source,
            discovered_at=discovered_at,
            discovery_kind=discovery_kind,
            raw_market=raw_market,
            market=market,
        )
        return MarketDiscoveryOutcome(
            trace_id=trace_id,
            source=source,
            classification=classification,
            event=event,
            market=market,
            discovery_kind=discovery_kind,
            subscription_request=subscription_request,
            raw_market=raw_market,
        )

    def _lookup_existing_market(
        self,
        classification: ClassificationResult,
    ) -> Market | None:
        if self._registry is None or not classification.accepted:
            return None
        if classification.condition_id is not None:
            market = self._registry.get_by_condition_id(classification.condition_id)
            if market is not None:
                return market
        if classification.market_slug is not None:
            return self._registry.get_by_slug(classification.market_slug)
        return None

    def _build_event(
        self,
        classification: ClassificationResult,
        *,
        trace_id: str,
        source: str,
        discovered_at: datetime,
        discovery_kind: str,
        raw_market: Mapping[str, Any],
        market: Market | None,
    ) -> DomainEvent:
        event_type = (
            DomainEventType.MARKET_UPDATED
            if classification.accepted and discovery_kind == DomainEventType.MARKET_UPDATED.value
            else (
                DomainEventType.MARKET_DISCOVERED
                if classification.accepted
                else DomainEventType.MARKET_FILTERED_OUT
            )
        )
        payload = {
            "source": source,
            "discovery_kind": discovery_kind,
            "classification_status": classification.status.value,
            "classification_reason": classification.reject_reason.value
            if classification.reject_reason
            else None,
            "classification_detail": classification.reject_detail,
            "matched_fields": classification.matched_fields,
            "matched_keywords": classification.matched_keywords,
            "accepted": classification.accepted,
            "market": _serialize_market(market),
            "raw_market": raw_market,
            "discovered_at": discovered_at.isoformat(),
        }
        return DomainEvent(
            trace_id=trace_id,
            event_type=event_type,
            event_id=uuid4().hex,
            market_slug=classification.market_slug,
            condition_id=classification.condition_id,
            reason=classification.reject_reason.value if classification.reject_reason else "",
            created_at=discovered_at,
            payload=payload,
        )


@dataclass(frozen=True, slots=True)
class MarketDiscoveryOutcome:
    trace_id: str
    source: str
    classification: ClassificationResult
    event: DomainEvent
    market: Market | None
    discovery_kind: str
    subscription_request: dict[str, Any] | None
    raw_market: Mapping[str, Any]

    @property
    def accepted(self) -> bool:
        return self.classification.accepted


def _serialize_market(market: Market | None) -> dict[str, Any] | None:
    if market is None:
        return None
    return {
        "condition_id": market.condition_id,
        "market_slug": market.market_slug,
        "no_token_id": market.no_token_id,
        "yes_token_id": market.yes_token_id,
        "event_id": market.event_id,
        "event_title": market.event_title,
        "event_slug": market.event_slug,
        "tick_size": str(market.tick_size),
        "min_order_size": str(market.min_order_size),
        "neg_risk": market.neg_risk,
        "category": market.category,
        "tags": market.tags,
        "matched_keywords": market.matched_keywords,
        "trading_status": market.trading_status.value,
        "reject_reason": market.reject_reason,
    }
