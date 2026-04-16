from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.order import (
    BuyOrderIntent,
    CancelOrderIntent,
    ReplaceOrderIntent,
    SellOrderIntent,
)
from polymarket_trader.domain.order import OrderType


class StrategyEngine:
    """Builds order intents from classified markets, orderbooks, and allocations."""

    def build_buy_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        token_id: str,
        price: Decimal,
        amount_usdc: Decimal,
        order_type: OrderType = OrderType.FAK,
        market_slug: str | None = None,
    ) -> BuyOrderIntent:
        return BuyOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=token_id,
            price=price,
            amount_usdc=amount_usdc,
            order_type=order_type,
            market_slug=market_slug,
        )

    def build_sell_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        token_id: str,
        price: Decimal,
        size_shares: Decimal,
        order_type: OrderType = OrderType.GTC,
        market_slug: str | None = None,
    ) -> SellOrderIntent:
        return SellOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=token_id,
            price=price,
            size_shares=size_shares,
            order_type=order_type,
            market_slug=market_slug,
        )

    def build_cancel_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        token_id: str,
        order_id: str,
        market_slug: str | None = None,
        reason: str = "",
    ) -> CancelOrderIntent:
        return CancelOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=token_id,
            order_id=order_id,
            market_slug=market_slug,
            reason=reason,
        )

    def build_replace_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        token_id: str,
        order_id: str,
        size_shares: Decimal,
        market_slug: str | None = None,
        new_price: Decimal,
        reason: str = "",
    ) -> ReplaceOrderIntent:
        return ReplaceOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=token_id,
            order_id=order_id,
            new_price=new_price,
            size_shares=size_shares,
            market_slug=market_slug,
            reason=reason,
        )
