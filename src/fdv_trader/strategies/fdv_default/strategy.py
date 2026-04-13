from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import OrderSide
from fdv_trader.strategy_api.models import (
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)
from fdv_trader.strategies.fdv_default.config import FDVDefaultStrategyConfig


class FDVDefaultStrategy:
    def __init__(self, config: FDVDefaultStrategyConfig | None = None) -> None:
        self._config = config or FDVDefaultStrategyConfig()
        self._spec = StrategySpec(
            name="fdv_default",
            version="1",
            description="Built-in FDV default strategy scaffold",
            config_type=FDVDefaultStrategyConfig,
            capabilities=("universe", "entry", "exit", "recovery"),
        )

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def select_market(self, market: Market) -> UniverseDecision:
        keywords = {keyword.lower() for keyword in market.matched_keywords}
        if market.category == "Crypto" and {"fdv", "500m"}.issubset(keywords):
            return UniverseDecision.include(reason="matched_fdv_default_universe")
        return UniverseDecision.exclude(reason="not_crypto_fdv_500m")

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        if context.market is None or context.orderbook is None:
            return StrategyDecision.skip(reason="missing_market_state")
        best_ask = context.orderbook.best_ask
        if best_ask is None:
            return StrategyDecision.skip(reason="missing_best_ask")
        if best_ask > self._config.entry_no_price_max:
            return StrategyDecision.skip(reason="price_above_entry_max")

        amount_usdc = _metadata_decimal(context, "amount_usdc", "buy_budget_usdc")
        if amount_usdc is None or amount_usdc <= Decimal("0"):
            return StrategyDecision.skip(reason="missing_entry_amount")

        return StrategyDecision.buy(
            reason="fdv_default_entry",
            price=self._config.entry_no_price_max,
            amount_usdc=amount_usdc,
            market_slug=context.market.market_slug,
        )

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        size_shares = _metadata_decimal(context, "size_shares")
        if size_shares is not None and size_shares > Decimal("0"):
            uncovered_shares = size_shares
        elif context.position is not None:
            uncovered_shares = context.position.shares - context.position.open_sell_shares
        else:
            return StrategyDecision.skip(reason="missing_position_state")
        if uncovered_shares <= Decimal("0"):
            return StrategyDecision.skip(reason="no_uncovered_shares")

        return StrategyDecision.sell(
            reason="fdv_default_exit",
            price=self._config.exit_no_price,
            size_shares=uncovered_shares,
            market_slug=(
                context.market.market_slug
                if context.market is not None
                else _metadata_text(context, "market_slug")
            ),
        )

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        if context.market is None:
            return RecoveryDecision(reason="missing_market_state")

        account_snapshot = context.account_snapshot
        position = context.position
        if position is None and account_snapshot is not None:
            position = account_snapshot.get_position(
                context.market.condition_id,
                context.market.no_token_id,
            )

        open_orders = context.open_orders
        if not open_orders and account_snapshot is not None:
            open_orders = account_snapshot.open_orders_for_market(
                context.market.condition_id,
                context.market.no_token_id,
            )

        cancel_order_ids = tuple(
            order_id
            for order in open_orders
            for order_id in (_order_identifier(order),)
            if order_id is not None and _is_open_buy(order)
        )
        pause_market = context.market.trading_status in {
            TradingStatus.PAUSED,
            TradingStatus.CLOSED,
            TradingStatus.RESOLVED,
        } or (
            account_snapshot is not None
            and account_snapshot.is_market_paused(context.market.condition_id)
        )
        pause_reason = "market_not_tradable" if pause_market else ""

        return RecoveryDecision(
            reason="fdv_default_recovery",
            target_sell_size_shares=position.shares if position is not None else Decimal("0"),
            cancel_order_ids=cancel_order_ids,
            pause_market=pause_market,
            pause_reason=pause_reason,
        )


def build_strategy(config_path: str | None = None) -> FDVDefaultStrategy:
    return FDVDefaultStrategy()


def _metadata_decimal(context: StrategyContext, *keys: str) -> Decimal | None:
    for key in keys:
        value = context.metadata.get(key)
        if value is None:
            continue
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return None
    return None


def _metadata_text(context: StrategyContext, *keys: str) -> str | None:
    for key in keys:
        value = context.metadata.get(key)
        if value is not None:
            return str(value)
    return None


def _order_identifier(order) -> str | None:
    return order.order_id or order.idempotency_key


def _is_open_buy(order) -> bool:
    return order.side == OrderSide.BUY and order.open
