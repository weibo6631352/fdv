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
