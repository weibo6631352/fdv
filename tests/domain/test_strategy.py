from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.order import OrderSide, OrderType
from polymarket_trader.domain.strategy import StrategyEngine

ENTRY_PRICE = Decimal("0.41")
EXIT_PRICE = Decimal("0.78")


def test_strategy_builds_fak_buy_intent() -> None:
    intent = StrategyEngine().build_buy_intent(
        trace_id="trace",
        condition_id="condition",
        token_id="token",
        price=ENTRY_PRICE,
        amount_usdc=Decimal("10"),
    )

    assert intent.side == OrderSide.BUY
    assert intent.order_type == OrderType.FAK
    assert intent.price == ENTRY_PRICE


def test_strategy_builds_gtc_sell_intent() -> None:
    intent = StrategyEngine().build_sell_intent(
        trace_id="trace",
        condition_id="condition",
        token_id="token",
        price=EXIT_PRICE,
        size_shares=Decimal("10"),
    )

    assert intent.side == OrderSide.SELL
    assert intent.order_type == OrderType.GTC
    assert intent.price == EXIT_PRICE
