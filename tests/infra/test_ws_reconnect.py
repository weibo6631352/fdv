from __future__ import annotations

import asyncio
from decimal import Decimal

from fdv_trader.domain.events import DomainEventType
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.runtime.event_bus import EventBus
from fdv_trader.runtime.registry import MarketRegistry
from fdv_trader.workers.market_ws_worker import MarketWsWorker


def _market() -> Market:
    return Market(
        condition_id="condition",
        market_slug="token-500m-fdv",
        no_token_id="no-token",
        yes_token_id="yes-token",
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        category="Crypto",
        matched_keywords=("crypto", "fdv", "500m"),
        trading_status=TradingStatus.ELIGIBLE,
    )


def test_market_ws_worker_emits_entry_touch_only_once() -> None:
    async def run() -> None:
        event_bus = EventBus()
        registry = MarketRegistry()
        worker = MarketWsWorker(event_bus=event_bus, registry=registry)
        market = _market()
        worker.track_market(market)

        first_events = await worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.55",
                "best_ask": "0.60",
                "best_bid_size": "100",
                "best_ask_size": "200",
            }
        )
        second_events = await worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.56",
                "best_ask": "0.59",
                "best_bid_size": "100",
                "best_ask_size": "200",
            }
        )

        assert [str(event.event_type) for event in first_events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
            DomainEventType.ENTRY_PRICE_TOUCHED.value,
        ]
        assert [str(event.event_type) for event in second_events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
        ]

        entry_event = await event_bus.next_trading_event()
        assert entry_event.event_type == DomainEventType.ENTRY_PRICE_TOUCHED

    asyncio.run(run())


def test_market_ws_worker_builds_official_subscription_payload() -> None:
    worker = MarketWsWorker()

    payload = worker.build_subscription_request(("no-token-1", "no-token-2"))

    assert payload == {
        "assets_ids": ["no-token-1", "no-token-2"],
        "type": "market",
        "custom_feature_enabled": True,
    }


def test_market_ws_worker_updates_tick_size_in_registry() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        worker = MarketWsWorker(registry=registry)
        market = _market()
        worker.track_market(market)

        await worker.handle_message(
            {
                "type": "tick_size_change",
                "token_id": market.no_token_id,
                "tick_size": "0.02",
            }
        )

        updated = registry.get_by_condition_id(market.condition_id)
        assert updated is not None
        assert updated.tick_size == Decimal("0.02")

    asyncio.run(run())


def test_market_ws_worker_handles_official_price_change_batch_payload() -> None:
    async def run() -> None:
        worker = MarketWsWorker()
        market = _market()
        worker.track_market(market)

        events = await worker.handle_message(
            {
                "event_type": "price_change",
                "market": market.condition_id,
                "price_changes": [
                    {
                        "asset_id": market.no_token_id,
                        "price": "0.59",
                        "size": "200",
                        "side": "SELL",
                        "best_bid": "0.55",
                        "best_ask": "0.59",
                    }
                ],
                "timestamp": "1757908892351",
            }
        )

        snapshot = worker.snapshot(market.no_token_id)
        assert snapshot is not None
        assert snapshot.best_bid == Decimal("0.55")
        assert snapshot.best_ask == Decimal("0.59")
        assert [str(event.event_type) for event in events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
            DomainEventType.ENTRY_PRICE_TOUCHED.value,
        ]

    asyncio.run(run())


def test_market_ws_worker_handles_official_market_resolved_payload_with_assets_ids() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        worker = MarketWsWorker(registry=registry)
        market = _market()
        worker.track_market(market)

        events = await worker.handle_message(
            {
                "event_type": "market_resolved",
                "market": market.condition_id,
                "assets_ids": [market.yes_token_id, market.no_token_id],
            }
        )

        assert [str(event.event_type) for event in events] == [
            DomainEventType.MARKET_RESOLVED_OR_DISABLED.value,
        ]
        assert worker.status_snapshot().resolved_token_ids == (market.no_token_id,)
        updated = registry.get_by_condition_id(market.condition_id)
        assert updated is not None
        assert updated.trading_status == TradingStatus.RESOLVED

    asyncio.run(run())


def test_market_ws_worker_waits_for_entry_threshold_then_overwrites_latest_snapshot() -> None:
    async def run() -> None:
        event_bus = EventBus()
        registry = MarketRegistry()
        worker = MarketWsWorker(event_bus=event_bus, registry=registry)
        market = _market()
        worker.track_market(market)

        below_threshold_events = await worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.57",
                "best_ask": "0.61",
                "best_bid_size": "100",
                "best_ask_size": "200",
            }
        )
        trigger_events = await worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.56",
                "best_ask": "0.60",
                "best_bid_size": "110",
                "best_ask_size": "210",
            }
        )
        followup_events = await worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.55",
                "best_ask": "0.59",
                "best_bid_size": "120",
                "best_ask_size": "220",
            }
        )

        assert [str(event.event_type) for event in below_threshold_events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
        ]
        assert [str(event.event_type) for event in trigger_events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
            DomainEventType.ENTRY_PRICE_TOUCHED.value,
        ]
        assert [str(event.event_type) for event in followup_events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
        ]

        snapshot = worker.snapshot(market.no_token_id)
        assert snapshot is not None
        assert snapshot.best_bid == Decimal("0.55")
        assert snapshot.best_ask == Decimal("0.59")
        assert worker.status_snapshot().entry_price_touched_token_ids == (market.no_token_id,)

        entry_event = await event_bus.next_trading_event()
        assert entry_event.event_type == DomainEventType.ENTRY_PRICE_TOUCHED

    asyncio.run(run())


def test_market_ws_worker_does_not_trigger_entry_touch_above_threshold() -> None:
    async def run() -> None:
        event_bus = EventBus()
        registry = MarketRegistry()
        worker = MarketWsWorker(event_bus=event_bus, registry=registry)
        market = _market()
        worker.track_market(market)

        events = await worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.57",
                "best_ask": "0.61",
                "best_bid_size": "100",
                "best_ask_size": "200",
            }
        )

        assert [str(event.event_type) for event in events] == [
            DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
        ]
        assert worker.status_snapshot().entry_price_touched_token_ids == ()
        assert event_bus.trading_queue_depth() == 0
        assert event_bus.maintenance_queue_depth() == 1

    asyncio.run(run())
