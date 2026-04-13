from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fdv_trader.domain.allocation import AllocationMarketSnapshot
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from fdv_trader.domain.position import Position
from fdv_trader.runtime.account_state import AccountSnapshot
from fdv_trader.strategy_api.models import StrategyAction, StrategyContext
from fdv_trader.strategies.template.strategy import build_strategy


def test_template_strategy_is_original_fdv_strategy() -> None:
    strategy = build_strategy()
    market = Market(
        condition_id="condition-1",
        market_slug="slug-1",
        no_token_id="no-1",
        yes_token_id="yes-1",
        category="Crypto",
        matched_keywords=("fdv", "500m"),
        trading_status=TradingStatus.ELIGIBLE,
    )
    orderbook = OrderbookSnapshot(
        token_id="no-1",
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.60"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("100")),),
        received_at=datetime.now(timezone.utc),
        market_slug="slug-1",
        condition_id="condition-1",
    )

    universe = strategy.select_market(market)
    decision = strategy.decide_entry(
        StrategyContext(
            trace_id="trace-template",
            market=market,
            orderbook=orderbook,
            metadata={"amount_usdc": Decimal("25")},
        )
    )

    assert universe.selected is True
    assert decision.action == StrategyAction.BUY
    assert decision.amount_usdc == Decimal("25")


def test_template_strategy_sizes_and_recovers_like_original_strategy() -> None:
    strategy = build_strategy()
    market = Market(
        condition_id="condition-1",
        market_slug="slug-1",
        no_token_id="no-1",
        yes_token_id="yes-1",
        category="Crypto",
        matched_keywords=("fdv", "500m"),
        trading_status=TradingStatus.PAUSED,
    )
    secondary = Market(
        condition_id="condition-2",
        market_slug="slug-2",
        no_token_id="no-2",
        yes_token_id="yes-2",
        category="Crypto",
        matched_keywords=("fdv", "500m"),
        trading_status=TradingStatus.ELIGIBLE,
    )
    received_at = datetime.now(timezone.utc)
    primary_orderbook = OrderbookSnapshot(
        token_id="no-1",
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.60"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("100")),),
        received_at=received_at,
        market_slug="slug-1",
        condition_id="condition-1",
    )
    secondary_orderbook = OrderbookSnapshot(
        token_id="no-2",
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.60"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("100")),),
        received_at=received_at,
        market_slug="slug-2",
        condition_id="condition-2",
    )
    position = Position(
        condition_id="condition-1",
        token_id="no-1",
        shares=Decimal("12"),
        cost_usdc=Decimal("6"),
        market_slug="slug-1",
    )
    account = AccountSnapshot(
        positions=(position,),
        paused_markets=("condition-1",),
    )

    sizing = strategy.size_entry(
        StrategyContext(
            trace_id="trace-template-size",
            market=market,
            orderbook=primary_orderbook,
            metadata={
                "candidate_snapshots": (
                    AllocationMarketSnapshot(market=market, orderbook=primary_orderbook),
                    AllocationMarketSnapshot(market=secondary, orderbook=secondary_orderbook),
                ),
                "portfolio_budget_usdc": Decimal("100"),
                "available_usdc": Decimal("100"),
                "max_order_usdc": Decimal("100"),
                "max_market_usdc": Decimal("100"),
                "max_total_usdc": Decimal("100"),
                "entry_no_price_max": Decimal("0.60"),
                "min_liquidity_usdc": Decimal("5"),
                "max_spread": Decimal("0.10"),
            },
        )
    )
    recovery = strategy.decide_recovery(
        StrategyContext(
            trace_id="trace-template-recovery",
            market=market,
            account_snapshot=account,
            position=position,
        )
    )

    assert sizing.eligible_market_count == 2
    assert sizing.allocation is not None
    assert sizing.allocation.buy_budget_usdc == Decimal("50")
    assert recovery.target_sell_size_shares == Decimal("12")
    assert recovery.pause_market is True
