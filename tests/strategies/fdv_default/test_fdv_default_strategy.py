from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from fdv_trader.domain.position import Position
from fdv_trader.runtime.account_state import AccountSnapshot
from fdv_trader.strategy_api.models import StrategyAction, StrategyContext
from fdv_trader.strategies.fdv_default.strategy import build_strategy


def test_fdv_default_strategy_can_be_loaded_and_decide_entry() -> None:
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
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("10")),),
        asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("10")),),
        received_at=datetime.now(timezone.utc),
        market_slug="slug-1",
        condition_id="condition-1",
    )

    universe = strategy.select_market(market)
    decision = strategy.decide_entry(
        StrategyContext(
            trace_id="trace-1",
            market=market,
            orderbook=orderbook,
            metadata={"amount_usdc": Decimal("25")},
        )
    )

    assert universe.selected is True
    assert decision.action == StrategyAction.BUY
    assert decision.amount_usdc == Decimal("25")


def test_fdv_default_strategy_recovery_returns_target_sell_and_pause_state() -> None:
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

    recovery = strategy.decide_recovery(
        StrategyContext(
            trace_id="trace-1",
            market=market,
            account_snapshot=account,
            position=position,
        )
    )

    assert recovery.target_sell_size_shares == Decimal("12")
    assert recovery.pause_market is True
