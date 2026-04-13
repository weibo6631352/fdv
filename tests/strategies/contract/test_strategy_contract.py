from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fdv_trader.domain.allocation import AllocationMarketSnapshot
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from fdv_trader.domain.position import Position
from fdv_trader.runtime.account_state import AccountSnapshot
from fdv_trader.strategy_api.models import EntrySizing, StrategyAction, StrategyContext
from fdv_trader.strategies.current.strategy import build_strategy as build_current_strategy
from fdv_trader.strategies.template.strategy import build_strategy as build_template_strategy


@pytest.mark.parametrize(
    ("strategy_factory", "market"),
    [
        (
            build_current_strategy,
            Market(
                condition_id="condition-current",
                market_slug="slug-current",
                no_token_id="no-current",
                yes_token_id="yes-current",
                category="Crypto",
                matched_keywords=("fdv", "500m"),
                trading_status=TradingStatus.ELIGIBLE,
            ),
        ),
        (
            build_template_strategy,
            Market(
                condition_id="condition-template",
                market_slug="slug-template",
                no_token_id="no-template",
                yes_token_id="yes-template",
                category="Crypto",
                matched_keywords=("fdv", "500m"),
                trading_status=TradingStatus.ELIGIBLE,
            ),
        ),
    ],
)
def test_strategy_contract_positive_path(strategy_factory, market: Market) -> None:
    strategy = strategy_factory()

    received_at = datetime.now(timezone.utc)
    orderbook = OrderbookSnapshot(
        token_id=market.no_token_id,
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.60"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("100")),),
        received_at=received_at,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        best_bid_size=Decimal("100"),
        best_ask_size=Decimal("100"),
        tick_size=market.tick_size,
    )
    position = Position(
        condition_id=market.condition_id,
        token_id=market.no_token_id,
        shares=Decimal("10"),
        cost_usdc=Decimal("5"),
        market_slug=market.market_slug,
    )
    account_snapshot = AccountSnapshot(
        positions=(position,),
        paused_markets=(),
    )

    universe = strategy.select_market(market)
    assert universe.selected is True

    sizing = strategy.size_entry(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            orderbook=orderbook,
            metadata={
                "candidate_snapshots": (
                    AllocationMarketSnapshot(market=market, orderbook=orderbook),
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
    assert isinstance(sizing, EntrySizing)
    assert sizing.allocation is not None
    assert sizing.allocation.buy_budget_usdc > Decimal("0")

    entry = strategy.decide_entry(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            orderbook=orderbook,
            metadata={"amount_usdc": Decimal("10")},
        )
    )
    assert entry.action == StrategyAction.BUY
    assert entry.amount_usdc == Decimal("10")

    exit_decision = strategy.decide_exit(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            position=position,
        )
    )
    assert exit_decision.action == StrategyAction.SELL

    recovery = strategy.decide_recovery(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            position=position,
            account_snapshot=account_snapshot,
        )
    )
    assert recovery.target_sell_size_shares == Decimal("10")
