from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from fdv_trader.app.strategy_service import StrategyService
from fdv_trader.app.trading_service import TradingService
from fdv_trader.domain.events import DomainEventType
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from fdv_trader.runtime.event_bus import EventBus
from fdv_trader.runtime.registry import MarketRegistry
from fdv_trader.workers.market_ws_worker import MarketWsWorker
from fdv_trader.workers.strategy_worker import StrategyWorker


def _market(
    *,
    condition_id: str,
    token_id: str,
    market_slug: str,
) -> Market:
    return Market(
        condition_id=condition_id,
        market_slug=market_slug,
        no_token_id=token_id,
        yes_token_id=f"yes-{token_id}",
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        category="Crypto",
        matched_keywords=("crypto", "fdv", "500m"),
        trading_status=TradingStatus.ELIGIBLE,
    )


def _snapshot(
    *,
    market: Market,
    best_bid: str = "0.55",
    best_ask: str = "0.60",
) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        token_id=market.no_token_id,
        best_bid=Decimal(best_bid),
        best_ask=Decimal(best_ask),
        bids=(PriceLevel(price=Decimal(best_bid), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal(best_ask), size=Decimal("200")),),
        received_at=datetime.now(timezone.utc),
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        best_bid_size=Decimal("100"),
        best_ask_size=Decimal("200"),
        tick_size=market.tick_size,
    )


def test_strategy_service_allocates_equally_across_eligible_markets() -> None:
    registry = MarketRegistry()
    primary = _market(condition_id="condition-1", token_id="no-1", market_slug="token-1")
    secondary = _market(condition_id="condition-2", token_id="no-2", market_slug="token-2")
    registry.upsert(primary)
    registry.upsert(secondary)
    snapshots = {
        primary.no_token_id: _snapshot(market=primary),
        secondary.no_token_id: _snapshot(market=secondary),
    }
    service = StrategyService(
        registry=registry,
        orderbook_reader=snapshots.get,
    )

    plan = service.build_entry_plan(
        condition_id=primary.condition_id,
        token_id=primary.no_token_id,
        trace_id="trace",
        portfolio_budget_usdc=Decimal("100"),
        available_usdc=Decimal("100"),
        max_order_usdc=Decimal("100"),
        max_market_usdc=Decimal("100"),
        max_total_usdc=Decimal("100"),
        min_liquidity_usdc=Decimal("5"),
        max_spread=Decimal("0.10"),
    )

    assert plan.ready_to_trade
    assert plan.eligible_market_count == 2
    assert plan.allocation is not None
    assert plan.allocation.buy_budget_usdc == Decimal("50")
    assert plan.intent is not None
    assert plan.intent.amount_usdc == Decimal("50")


def test_strategy_worker_turns_entry_price_touch_into_risk_result() -> None:
    async def run() -> None:
        event_bus = EventBus()
        registry = MarketRegistry()
        market_ws_worker = MarketWsWorker(event_bus=event_bus, registry=registry)
        market = _market(condition_id="condition", token_id="no-token", market_slug="token")
        market_ws_worker.track_market(market)

        strategy_service = StrategyService(
            registry=registry,
            orderbook_reader=market_ws_worker.snapshot,
        )
        strategy_worker = StrategyWorker(
            event_bus=event_bus,
            strategy_service=strategy_service,
            trading_service=TradingService(),
            portfolio_budget_usdc=Decimal("100"),
            available_usdc=Decimal("100"),
            max_order_usdc=Decimal("100"),
            max_market_usdc=Decimal("100"),
            max_total_usdc=Decimal("100"),
            min_liquidity_usdc=Decimal("5"),
            max_spread=Decimal("0.10"),
            balance_usdc=Decimal("100"),
            allowance_usdc=Decimal("100"),
            max_open_orders=10,
            order_retry_limit=2,
        )

        await market_ws_worker.handle_message(
            {
                "type": "best_bid_ask",
                "token_id": market.no_token_id,
                "best_bid": "0.55",
                "best_ask": "0.60",
                "best_bid_size": "100",
                "best_ask_size": "200",
            }
        )
        entry_event = await event_bus.next_trading_event()
        result = await strategy_worker.process_event(entry_event)

        assert result is not None
        assert result.plan.ready_to_trade
        assert result.review is not None
        assert result.review.risk_decision.passed
        assert result.emitted_event.event_type == DomainEventType.RISK_CHECK_PASSED

    asyncio.run(run())
