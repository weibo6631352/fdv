from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from polymarket_trader.domain.classifier import ClassificationResult, MarketClassifier
from polymarket_trader.domain.events import DomainEvent, DomainEventType
from polymarket_trader.domain.market import Market
from polymarket_trader.observability.trace import ensure_trace_id
from polymarket_trader.runtime.account_state import AccountSnapshot
from polymarket_trader.runtime.registry import MarketRegistry
from strategy_sdk import StrategyModule, UniverseDecision

AccountSnapshotProvider = Callable[[], AccountSnapshot]


class MarketService:
    """Coordinates market discovery, strategy universe filtering, and registry updates."""

    def __init__(
        self,
        *,
        strategy_module: StrategyModule,
        classifier: MarketClassifier | None = None,
        registry: MarketRegistry | None = None,
        market_tracker: Any | None = None,
        account_snapshot_provider: AccountSnapshotProvider | None = None,
    ) -> None:
        self._classifier = classifier or MarketClassifier()
        self._strategy_module = strategy_module
        self._registry = registry
        self._market_tracker = market_tracker
        self._account_snapshot_provider = account_snapshot_provider

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
        account_snapshot = self._current_account_snapshot()

        market: Market | None = None
        tracked_market: Market | None = None
        tracking_retained = False
        subscription_request: dict[str, Any] | None = None
        universe_decision: UniverseDecision | None = None
        if classification.accepted:
            candidate_market = classification.to_market()
            if existing_market is not None:
                candidate_market = candidate_market.with_fee_schedule(
                    fees_enabled=(
                        candidate_market.fees_enabled
                        if candidate_market.fees_enabled is not None
                        else existing_market.fees_enabled
                    ),
                    maker_base_fee_bps=(
                        candidate_market.maker_base_fee_bps
                        if candidate_market.maker_base_fee_bps is not None
                        else existing_market.maker_base_fee_bps
                    ),
                    taker_base_fee_bps=(
                        candidate_market.taker_base_fee_bps
                        if candidate_market.taker_base_fee_bps is not None
                        else existing_market.taker_base_fee_bps
                    ),
                )
                if existing_market.fee_rate_bps is not None:
                    candidate_market = candidate_market.with_fee_rate(
                        existing_market.fee_rate_bps,
                        fee_rate_updated_at=existing_market.fee_rate_updated_at,
                    )

            universe_decision = self._strategy_module.select_market(candidate_market)
            if universe_decision.selected:
                market = candidate_market
                tracked_market = market
                if self._registry is not None:
                    self._registry.upsert(market)
                if self._market_tracker is not None:
                    self._market_tracker.track_market(market)
                    if hasattr(self._market_tracker, "build_subscription_request"):
                        subscription_request = self._market_tracker.build_subscription_request(
                            market.no_token_id
                        )
            elif existing_market is not None:
                if self._should_retain_filtered_market(existing_market, account_snapshot):
                    tracked_market = self._build_retained_filtered_market(
                        candidate_market,
                        existing_market=existing_market,
                        reason=universe_decision.reason,
                    )
                    tracking_retained = True
                    if self._registry is not None:
                        self._registry.upsert(tracked_market)
                    if self._market_tracker is not None:
                        self._market_tracker.track_market(tracked_market)
                else:
                    self._remove_market_tracking(existing_market)

        discovery_kind = (
            DomainEventType.MARKET_UPDATED.value
            if market is not None and existing_market is not None
            else (
                DomainEventType.MARKET_DISCOVERED.value
                if market is not None
                else DomainEventType.MARKET_FILTERED_OUT.value
            )
        )
        event = self._build_event(
            classification,
            trace_id=trace_id,
            source=source,
            discovered_at=discovered_at,
            discovery_kind=discovery_kind,
            raw_market=raw_market,
            market=market,
            tracked_market=tracked_market,
            tracking_retained=tracking_retained,
            universe_decision=universe_decision,
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
            tracked_market=tracked_market,
            tracking_retained=tracking_retained,
            universe_decision=universe_decision,
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
        tracked_market: Market | None,
        tracking_retained: bool,
        universe_decision: UniverseDecision | None,
    ) -> DomainEvent:
        event_type = (
            DomainEventType.MARKET_UPDATED
            if market is not None and discovery_kind == DomainEventType.MARKET_UPDATED.value
            else (
                DomainEventType.MARKET_DISCOVERED
                if market is not None
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
            "accepted": market is not None,
            "strategy_selected": universe_decision.selected if universe_decision is not None else None,
            "strategy_reason": universe_decision.reason if universe_decision is not None else None,
            "market": _serialize_market(market),
            "tracked_market": _serialize_market(tracked_market),
            "tracking_retained": tracking_retained,
            "raw_market": raw_market,
            "discovered_at": discovered_at.isoformat(),
        }
        return DomainEvent(
            trace_id=trace_id,
            event_type=event_type,
            event_id=uuid4().hex,
            market_slug=classification.market_slug,
            condition_id=classification.condition_id,
            reason=self._event_reason(classification, universe_decision),
            created_at=discovered_at,
            payload=payload,
        )

    @staticmethod
    def _event_reason(
        classification: ClassificationResult,
        universe_decision: UniverseDecision | None,
    ) -> str:
        if universe_decision is not None and not universe_decision.selected:
            return universe_decision.reason
        if classification.reject_reason is not None:
            return classification.reject_reason.value
        return ""

    def _current_account_snapshot(self) -> AccountSnapshot | None:
        if self._account_snapshot_provider is None:
            return None
        return self._account_snapshot_provider()

    def _should_retain_filtered_market(
        self,
        market: Market,
        account_snapshot: AccountSnapshot | None,
    ) -> bool:
        return self._strategy_module.should_keep_tracking(market, account_snapshot)

    def _build_retained_filtered_market(
        self,
        candidate_market: Market,
        *,
        existing_market: Market,
        reason: str,
    ) -> Market:
        return self._strategy_module.build_filtered_tracking_market(
            candidate_market,
            existing_market=existing_market,
            reason=reason,
        )

    def _remove_market_tracking(self, market: Market) -> None:
        if self._registry is not None:
            self._registry.remove_market(market.condition_id)
        if self._market_tracker is not None and hasattr(self._market_tracker, "untrack_market"):
            self._market_tracker.untrack_market(market.no_token_id)


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
    tracked_market: Market | None = None
    tracking_retained: bool = False
    universe_decision: UniverseDecision | None = None

    @property
    def accepted(self) -> bool:
        return self.market is not None


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
        "fees": {
            "enabled": market.fees_enabled,
            "maker_base_fee_bps": market.maker_base_fee_bps,
            "taker_base_fee_bps": market.taker_base_fee_bps,
            "fee_rate_bps": market.fee_rate_bps,
            "fee_rate_updated_at": (
                None
                if market.fee_rate_updated_at is None
                else market.fee_rate_updated_at.isoformat()
            ),
        },
        "category": market.category,
        "tags": market.tags,
        "matched_keywords": market.matched_keywords,
        "trading_status": market.trading_status.value,
        "reject_reason": market.reject_reason,
    }
