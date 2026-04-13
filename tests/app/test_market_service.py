from __future__ import annotations

from polymarket_trader.app.market_service import MarketService
from polymarket_trader.domain.events import DomainEventType
from polymarket_trader.runtime.registry import MarketRegistry
from polymarket_trader.strategy_api.models import UniverseDecision


class _Tracker:
    def __init__(self) -> None:
        self.markets = []

    def track_market(self, market) -> None:
        self.markets.append(market)

    def build_subscription_request(self, token_id: str) -> dict[str, object]:
        return {
            "channel": "market",
            "token_ids": [token_id],
            "custom_feature_enabled": True,
        }


def _raw_market(*, condition_id: str = "condition", market_slug: str = "sample-market-a") -> dict[str, str]:
    return {
        "category": "Crypto",
        "event_title": "Will this market reach a threshold?",
        "question": "Will this market hit a threshold?",
        "market_slug": market_slug,
        "condition_id": condition_id,
        "yes_token_id": "yes-token",
        "no_token_id": f"no-{condition_id}",
        "tick_size": "0.01",
        "min_order_size": "1",
    }


def test_market_service_ingests_market_into_registry_and_tracker() -> None:
    registry = MarketRegistry()
    tracker = _Tracker()
    service = MarketService(registry=registry, market_tracker=tracker)

    outcome = service.ingest_raw_market(_raw_market(), source="gamma", trace_id="trace")

    assert outcome.accepted
    assert outcome.market is not None
    assert outcome.discovery_kind == DomainEventType.MARKET_DISCOVERED.value
    assert outcome.event.event_type == DomainEventType.MARKET_DISCOVERED
    assert registry.get_by_condition_id("condition") == outcome.market
    assert tracker.markets == [outcome.market]
    assert outcome.subscription_request == tracker.build_subscription_request("no-condition")


def test_market_service_marks_existing_market_as_updated() -> None:
    registry = MarketRegistry()
    service = MarketService(registry=registry)

    first = service.ingest_raw_market(_raw_market(), source="gamma", trace_id="trace-1")
    second = service.ingest_raw_market(_raw_market(), source="gamma", trace_id="trace-2")

    assert first.accepted
    assert second.accepted
    assert second.discovery_kind == DomainEventType.MARKET_UPDATED.value
    assert second.event.event_type == DomainEventType.MARKET_UPDATED


def test_market_service_respects_strategy_universe_filter() -> None:
    class _RejectingStrategy:
        @property
        def spec(self):
            from polymarket_trader.strategy_api.models import StrategySpec

            return StrategySpec(name="rejecting")

        def select_market(self, market):
            return UniverseDecision.exclude(reason="strategy_filtered_out")

        def decide_entry(self, context):
            raise AssertionError("not used")

        def decide_exit(self, context):
            raise AssertionError("not used")

        def decide_recovery(self, context):
            raise AssertionError("not used")

    registry = MarketRegistry()
    tracker = _Tracker()
    service = MarketService(
        strategy_module=_RejectingStrategy(),
        registry=registry,
        market_tracker=tracker,
    )

    outcome = service.ingest_raw_market(_raw_market(), source="gamma", trace_id="trace")

    assert outcome.accepted is False
    assert outcome.market is None
    assert outcome.event.event_type == DomainEventType.MARKET_FILTERED_OUT
    assert outcome.event.reason == "strategy_filtered_out"
    assert tracker.markets == []
