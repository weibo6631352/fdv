from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.constants import ENTRY_NO_PRICE_MAX, EXIT_NO_PRICE
from fdv_trader.domain.order import (
    BuyOrderIntent,
    CancelOrderIntent,
    ReplaceOrderIntent,
    SellOrderIntent,
)


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
    ) -> BuyOrderIntent:
        return BuyOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
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
    ) -> SellOrderIntent:
        return SellOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
            price=EXIT_NO_PRICE,
            size_shares=size_shares,
            market_slug=market_slug,
        )

    def build_cancel_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        order_id: str,
        market_slug: str | None = None,
        reason: str = "",
    ) -> CancelOrderIntent:
        return CancelOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
            order_id=order_id,
            market_slug=market_slug,
            reason=reason,
        )

    def build_replace_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        order_id: str,
        size_shares: Decimal,
        market_slug: str | None = None,
        new_price: Decimal = EXIT_NO_PRICE,
        reason: str = "",
    ) -> ReplaceOrderIntent:
        return ReplaceOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
            order_id=order_id,
            new_price=new_price,
            size_shares=size_shares,
            market_slug=market_slug,
            reason=reason,
        )
