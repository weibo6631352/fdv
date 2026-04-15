from __future__ import annotations

import asyncio

from polymarket_trader.app.market_service import MarketService
from polymarket_trader.domain.events import DomainEventType
from polymarket_trader.infra.outbox import LocalOutbox, build_domain_event_outbox_sink
from polymarket_trader.runtime.event_bus import EventBus
from polymarket_trader.workers.market_discovery_worker import MarketDiscoveryWorker
from strategy_sdk.models import StrategyRuntimeProfile, StrategySpec, UniverseDecision


class _RejectingStrategy:
    @property
    def spec(self):
        return StrategySpec(name="rejecting")

    @property
    def runtime_profile(self):
        return StrategyRuntimeProfile()

    def build_discovery_queries(self):
        return ()

    def select_market(self, market):
        return UniverseDecision.exclude(reason="strategy_filtered_out")

    def size_entry(self, context):
        raise AssertionError("not used")

    def decide_entry(self, context):
        raise AssertionError("not used")

    def decide_exit(self, context):
        raise AssertionError("not used")

    def decide_recovery(self, context):
        raise AssertionError("not used")

    def should_keep_tracking(self, market, account_snapshot):
        return False

    def build_filtered_tracking_market(self, candidate_market, *, existing_market, reason):
        raise AssertionError("not used")


def test_market_discovery_worker_routes_filtered_out_events_to_persistence_only() -> None:
    async def run() -> None:
        event_bus = EventBus()
        outbox = LocalOutbox(max_size=8)
        event_bus.bind_persistence_sink(build_domain_event_outbox_sink(outbox))
        worker = MarketDiscoveryWorker(
            market_service=MarketService(strategy_module=_RejectingStrategy()),
            event_bus=event_bus,
        )

        events = await worker.ingest_source_page(
            {
                "events": [
                    {
                        "markets": [
                            {
                                "conditionId": "condition-1",
                                "slug": "sample-market-a",
                                "eventTitle": "Sample FDV Event",
                                "question": "Will this project hit $500M FDV?",
                                "tags": [{"label": "Crypto", "slug": "crypto"}],
                                "clobTokenIds": ["yes-1", "no-1"],
                                "orderPriceMinTickSize": "0.01",
                                "orderMinSize": "1",
                            }
                        ]
                    }
                ]
            },
            source="gamma",
            trace_id="trace-1",
        )

        assert len(events) == 1
        assert events[0].event_type == DomainEventType.MARKET_FILTERED_OUT
        assert event_bus.snapshot().maintenance_queue_depth == 0
        queued = await outbox.get()
        assert queued.priority == 3
        assert queued.event_type == DomainEventType.MARKET_FILTERED_OUT.value

    asyncio.run(run())
