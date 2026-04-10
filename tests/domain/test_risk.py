from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.constants import ENTRY_NO_PRICE_MAX
from fdv_trader.domain.order import OrderIntent, OrderSide, OrderType
from fdv_trader.domain.risk import RiskManager


def test_risk_rejects_intent_without_amount_or_size() -> None:
    intent = OrderIntent(
        trace_id="trace",
        condition_id="condition",
        token_id="token",
        side=OrderSide.BUY,
        order_type=OrderType.FAK,
        price=ENTRY_NO_PRICE_MAX,
        amount_usdc=None,
        size_shares=None,
    )

    assert not RiskManager().check_order_intent(intent).passed


def test_risk_accepts_intent_with_amount() -> None:
    intent = OrderIntent(
        trace_id="trace",
        condition_id="condition",
        token_id="token",
        side=OrderSide.BUY,
        order_type=OrderType.FAK,
        price=ENTRY_NO_PRICE_MAX,
        amount_usdc=Decimal("1"),
    )

    assert RiskManager().check_order_intent(intent).passed

