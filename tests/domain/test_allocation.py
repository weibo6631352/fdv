from __future__ import annotations

from decimal import Decimal

from datetime import datetime, timezone

from fdv_trader.domain.allocation import AllocationMarketSnapshot, AllocationPlan, equal_weight_budget
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel


def _market(condition_id: str, market_slug: str, no_token_id: str) -> Market:
    return Market(
        condition_id=condition_id,
        market_slug=market_slug,
        no_token_id=no_token_id,
        yes_token_id=f"yes-{no_token_id}",
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        category="Crypto",
        matched_keywords=("crypto", "fdv", "500m"),
        trading_status=TradingStatus.ELIGIBLE,
    )


def _snapshot(market: Market) -> AllocationMarketSnapshot:
    orderbook = OrderbookSnapshot(
        token_id=market.no_token_id,
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
    return AllocationMarketSnapshot(
        market=market,
        orderbook=orderbook,
        classification_passed=True,
        tradable=True,
        market_active=True,
        market_open=True,
        clob_enabled=True,
        best_ask=Decimal("0.60"),
        liquidity_usdc=Decimal("60"),
        spread=Decimal("0.05"),
    )


def test_equal_weight_budget_returns_zero_without_eligible_markets() -> None:
    assert equal_weight_budget(Decimal("100"), 0) == Decimal("0")


def test_equal_weight_plan_respects_per_market_cap_and_releases_budget() -> None:
    first = _snapshot(_market("condition-1", "token-1", "no-1"))
    second = _snapshot(_market("condition-2", "token-2", "no-2"))

    plan = AllocationPlan.equal_weight(
        trace_id="trace",
        portfolio_budget_usdc=Decimal("100"),
        markets=(first, second),
        available_usdc=Decimal("100"),
        max_order_usdc=Decimal("100"),
        max_market_usdc=Decimal("20"),
        max_total_usdc=Decimal("100"),
        entry_no_price_max=Decimal("0.60"),
        min_liquidity_usdc=Decimal("5"),
        max_spread=Decimal("0.10"),
    )

    assert plan.eligible_market_count == 2
    assert all(allocation.buy_budget_usdc <= Decimal("20") for allocation in plan.allocations)
    assert plan.released_budget_usdc == Decimal("60")
