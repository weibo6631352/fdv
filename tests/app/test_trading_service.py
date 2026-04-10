from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from fdv_trader.app.trading_service import TradingService
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import BuyOrderIntent
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel


def test_trading_service_reviews_intent_with_risk_manager() -> None:
    async def run() -> None:
        service = TradingService()
        market = Market(
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
        orderbook = OrderbookSnapshot(
            token_id="no-token",
            best_bid=Decimal("0.55"),
            best_ask=Decimal("0.60"),
            bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
            asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("100")),),
            received_at=datetime.now(timezone.utc),
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            best_bid_size=Decimal("100"),
            best_ask_size=Decimal("100"),
            tick_size=market.tick_size,
        )
        intent = BuyOrderIntent(
            trace_id="trace",
            condition_id=market.condition_id,
            token_id=market.no_token_id,
            price=Decimal("0.60"),
            amount_usdc=Decimal("10"),
            market_slug=market.market_slug,
        )

        result = await service.review_intent(
            intent,
            market=market,
            orderbook=orderbook,
            balance_usdc=Decimal("100"),
            allowance_usdc=Decimal("100"),
            max_order_usdc=Decimal("20"),
            max_market_usdc=Decimal("50"),
            max_total_usdc=Decimal("100"),
            max_open_orders=10,
            order_retry_limit=2,
            min_liquidity_usdc=Decimal("5"),
            max_spread=Decimal("0.10"),
        )

        assert result.risk_decision.passed
        assert not result.submitted
        assert result.submission_error is None

    asyncio.run(run())
