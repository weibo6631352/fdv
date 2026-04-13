from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import (
    BuyOrderIntent,
    CancelOrderIntent,
    Order,
    OrderSide,
    ReplaceOrderIntent,
    SellOrderIntent,
)
from fdv_trader.domain.position import Position
from fdv_trader.domain.strategy import StrategyEngine
from fdv_trader.runtime.account_state import AccountSnapshot
from fdv_trader.runtime.registry import MarketRegistrySnapshot
from fdv_trader.strategies.fdv_default.strategy import FDVDefaultStrategy
from fdv_trader.strategy_api.interfaces import StrategyModule
from fdv_trader.strategy_api.models import StrategyAction, StrategyContext, StrategyDecision


class ReconcileActionType(StrEnum):
    CANCEL_OPEN_BUY = "cancel_open_buy"
    SUBMIT_MISSING_SELL = "submit_missing_sell"
    CANCEL_EXCESS_SELL = "cancel_excess_sell"
    PAUSE_TRADING = "pause_trading"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _order_open_size(order: Order) -> Decimal:
    if order.remaining_shares is not None:
        return max(order.remaining_shares, Decimal("0"))
    if order.size_shares is not None:
        return max(order.size_shares, Decimal("0"))
    if order.amount_usdc is not None:
        return max(order.amount_usdc, Decimal("0"))
    return Decimal("0")


def _order_created_at(order: Order) -> datetime:
    return order.created_at or datetime.max.replace(tzinfo=timezone.utc)


def _normalize_order_id(order: Order) -> str:
    return order.order_id or order.idempotency_key or (
        f"{order.condition_id}:{order.token_id}:{order.side.value}:{order.status.value}"
    )


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    action_type: ReconcileActionType
    trace_id: str
    condition_id: str
    token_id: str
    market_slug: str | None
    reason: str
    source_order_id: str | None = None
    source_order_side: OrderSide | None = None
    target_size_shares: Decimal | None = None
    target_notional_usdc: Decimal | None = None
    pause_reason: str | None = None
    intent: BuyOrderIntent | SellOrderIntent | CancelOrderIntent | ReplaceOrderIntent | None = None

    @property
    def priority(self) -> int:
        if self.action_type == ReconcileActionType.PAUSE_TRADING:
            return 1
        return 2

    @property
    def merge_key(self) -> str:
        return "|".join(
            (
                self.action_type.value,
                self.condition_id,
                self.token_id,
                self.source_order_id or "",
                self.reason,
            )
        )


@dataclass(frozen=True, slots=True)
class ReconcileMarketPlan:
    trace_id: str
    market: Market
    position: Position | None
    open_buy_orders: tuple[Order, ...]
    open_sell_orders: tuple[Order, ...]
    actions: tuple[ReconcileAction, ...]
    pause_trading: bool
    pause_reason: str | None = None

    @property
    def has_changes(self) -> bool:
        return bool(self.actions) or self.pause_trading


@dataclass(frozen=True, slots=True)
class ReconcilePlan:
    trace_id: str
    generated_at: datetime
    market_plans: tuple[ReconcileMarketPlan, ...]
    total_actions: int
    paused_markets: int

    @property
    def diff_count(self) -> int:
        return self.total_actions

    @property
    def has_changes(self) -> bool:
        return self.total_actions > 0 or self.paused_markets > 0


class ReconcileService:
    """Builds reconcile diffs and strategy-driven repair intents from hot snapshots."""

    def __init__(
        self,
        *,
        strategy_module: StrategyModule | None = None,
        strategy_engine: StrategyEngine | None = None,
    ) -> None:
        self._strategy_module = strategy_module or FDVDefaultStrategy()
        self._strategy_engine = strategy_engine or StrategyEngine()

    def build_reconcile_plan(
        self,
        *,
        registry_snapshot: MarketRegistrySnapshot,
        account_snapshot: AccountSnapshot,
        trace_id: str | None = None,
        condition_ids: tuple[str, ...] | None = None,
    ) -> ReconcilePlan:
        trace_id = trace_id or uuid4().hex
        markets = registry_snapshot.markets
        if condition_ids is not None:
            condition_id_set = set(condition_ids)
            markets = tuple(market for market in markets if market.condition_id in condition_id_set)

        market_plans = tuple(
            self.build_market_plan(
                market=market,
                account_snapshot=account_snapshot,
                trace_id=trace_id,
            )
            for market in markets
        )
        total_actions = sum(len(plan.actions) for plan in market_plans)
        paused_markets = sum(1 for plan in market_plans if plan.pause_trading)
        return ReconcilePlan(
            trace_id=trace_id,
            generated_at=_utc_now(),
            market_plans=market_plans,
            total_actions=total_actions,
            paused_markets=paused_markets,
        )

    def build_market_plan(
        self,
        *,
        market: Market,
        account_snapshot: AccountSnapshot,
        trace_id: str | None = None,
    ) -> ReconcileMarketPlan:
        trace_id = trace_id or uuid4().hex
        position = account_snapshot.get_position(market.condition_id, market.no_token_id)
        open_buy_orders = account_snapshot.open_buy_orders_for_market(
            market.condition_id,
            market.no_token_id,
        )
        open_sell_orders = account_snapshot.open_sell_orders_for_market(
            market.condition_id,
            market.no_token_id,
        )
        recovery = self._strategy_module.decide_recovery(
            StrategyContext(
                trace_id=trace_id,
                market=market,
                account_snapshot=account_snapshot,
                position=position,
                open_orders=tuple((*open_buy_orders, *open_sell_orders)),
            )
        )

        pause_trading = (
            market.trading_status in {TradingStatus.PAUSED, TradingStatus.CLOSED, TradingStatus.RESOLVED}
            or account_snapshot.is_market_paused(market.condition_id)
            or recovery.pause_market
        )
        pause_reason = recovery.pause_reason or _pause_reason(market, account_snapshot)

        actions: list[ReconcileAction] = []
        cancel_order_ids = set(recovery.cancel_order_ids)

        for order in open_buy_orders:
            order_id = _normalize_order_id(order)
            if cancel_order_ids and order_id not in cancel_order_ids:
                continue
            actions.append(
                ReconcileAction(
                    action_type=ReconcileActionType.CANCEL_OPEN_BUY,
                    trace_id=trace_id,
                    condition_id=market.condition_id,
                    token_id=market.no_token_id,
                    market_slug=market.market_slug,
                    reason=order.reason or "open_buy_detected",
                    source_order_id=order_id,
                    source_order_side=order.side,
                    intent=self._strategy_engine.build_cancel_intent(
                        trace_id=trace_id,
                        condition_id=market.condition_id,
                        no_token_id=market.no_token_id,
                        order_id=order_id,
                        market_slug=market.market_slug,
                        reason=order.reason or "open_buy_detected",
                    ),
                )
            )

        target_sell_shares = max(recovery.target_sell_size_shares, Decimal("0"))
        open_sell_shares = sum((_order_open_size(order) for order in open_sell_orders), Decimal("0"))

        shortage = max(target_sell_shares - open_sell_shares, Decimal("0"))
        if shortage > Decimal("0"):
            sell_intent = _decision_to_sell_intent(
                trace_id=trace_id,
                market=market,
                decision=self._strategy_module.decide_exit(
                    StrategyContext(
                        trace_id=trace_id,
                        market=market,
                        account_snapshot=account_snapshot,
                        position=position,
                        open_orders=open_sell_orders,
                        metadata={"size_shares": shortage},
                    )
                ),
            ) or self._strategy_engine.build_sell_intent(
                trace_id=trace_id,
                condition_id=market.condition_id,
                no_token_id=market.no_token_id,
                size_shares=shortage,
                market_slug=market.market_slug,
            )
            actions.append(
                ReconcileAction(
                    action_type=ReconcileActionType.SUBMIT_MISSING_SELL,
                    trace_id=trace_id,
                    condition_id=market.condition_id,
                    token_id=market.no_token_id,
                    market_slug=market.market_slug,
                    reason="sell_coverage_short",
                    target_size_shares=shortage,
                    target_notional_usdc=shortage * sell_intent.price,
                    intent=sell_intent,
                )
            )

        excess = max(open_sell_shares - target_sell_shares, Decimal("0"))
        if excess > Decimal("0"):
            for order in self._select_sell_cancellations(open_sell_orders, excess):
                order_id = _normalize_order_id(order)
                actions.append(
                    ReconcileAction(
                        action_type=ReconcileActionType.CANCEL_EXCESS_SELL,
                        trace_id=trace_id,
                        condition_id=market.condition_id,
                        token_id=market.no_token_id,
                        market_slug=market.market_slug,
                        reason="sell_coverage_excess",
                        source_order_id=order_id,
                        source_order_side=order.side,
                        target_size_shares=_order_open_size(order),
                        intent=self._strategy_engine.build_cancel_intent(
                            trace_id=trace_id,
                            condition_id=market.condition_id,
                            no_token_id=market.no_token_id,
                            order_id=order_id,
                            market_slug=market.market_slug,
                            reason="sell_coverage_excess",
                        ),
                    )
                )

        if pause_trading:
            actions.append(
                ReconcileAction(
                    action_type=ReconcileActionType.PAUSE_TRADING,
                    trace_id=trace_id,
                    condition_id=market.condition_id,
                    token_id=market.no_token_id,
                    market_slug=market.market_slug,
                    reason="market_not_tradable",
                    pause_reason=pause_reason,
                )
            )

        return ReconcileMarketPlan(
            trace_id=trace_id,
            market=market,
            position=position,
            open_buy_orders=open_buy_orders,
            open_sell_orders=open_sell_orders,
            actions=tuple(actions),
            pause_trading=pause_trading,
            pause_reason=pause_reason,
        )

    def _select_sell_cancellations(
        self,
        open_sell_orders: tuple[Order, ...],
        excess: Decimal,
    ) -> tuple[Order, ...]:
        selected: list[Order] = []
        remaining_excess = excess
        for order in sorted(
            open_sell_orders,
            key=lambda item: (
                _order_open_size(item),
                _order_created_at(item),
                _normalize_order_id(item),
            ),
        ):
            if remaining_excess <= Decimal("0"):
                break
            selected.append(order)
            remaining_excess -= _order_open_size(order)
        return tuple(selected)


def _position_shares(position: Position | None) -> Decimal:
    if position is None:
        return Decimal("0")
    return max(position.shares, Decimal("0"))


def _pause_reason(market: Market, account_snapshot: AccountSnapshot) -> str:
    if market.trading_status == TradingStatus.PAUSED:
        return market.reject_reason or "market_paused"
    if market.trading_status == TradingStatus.CLOSED:
        return market.reject_reason or "market_closed"
    if market.trading_status == TradingStatus.RESOLVED:
        return market.reject_reason or "market_resolved"
    if account_snapshot.is_market_paused(market.condition_id):
        return dict(account_snapshot.pause_reasons).get(market.condition_id, "manual_pause")
    return ""


def _decision_to_sell_intent(
    *,
    trace_id: str,
    market: Market,
    decision: StrategyDecision,
) -> SellOrderIntent | None:
    if decision.action != StrategyAction.SELL:
        return None
    if decision.price is None or decision.size_shares is None or decision.size_shares <= Decimal("0"):
        return None
    return SellOrderIntent(
        trace_id=trace_id,
        condition_id=market.condition_id,
        token_id=market.no_token_id,
        price=decision.price,
        size_shares=decision.size_shares,
        market_slug=decision.market_slug or market.market_slug,
    )
