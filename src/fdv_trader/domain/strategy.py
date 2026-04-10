from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.constants import ENTRY_NO_PRICE_MAX, EXIT_NO_PRICE
from fdv_trader.domain.order import OrderIntent, OrderSide, OrderType


class StrategyEngine:
    """Builds order intents from classified markets, orderbooks, and allocations."""

    def build_buy_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        amount_usdc: Decimal,
        market_slug: str | None = None,
    ) -> OrderIntent:
        return OrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
            side=OrderSide.BUY,
            order_type=OrderType.FAK,
            price=ENTRY_NO_PRICE_MAX,
            amount_usdc=amount_usdc,
            market_slug=market_slug,
        )

    def build_sell_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        size_shares: Decimal,
        market_slug: str | None = None,
    ) -> OrderIntent:
        return OrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
            side=OrderSide.SELL,
            order_type=OrderType.GTC,
            price=EXIT_NO_PRICE,
            size_shares=size_shares,
            market_slug=market_slug,
        )

