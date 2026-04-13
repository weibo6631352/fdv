from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from polymarket_trader.domain.allocation import AllocationPlan, current_exposure_usdc
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import Order, OrderIntent, OrderSide, OrderStatus
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.domain.position import Position


@dataclass(frozen=True, slots=True)
class RiskCheck:
    name: str
    passed: bool
    reason: str = ""
    field: str | None = None
    value: object | None = None
    suggested_action: str = ""
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class RiskDecision:
    passed: bool
    reason: str = ""
    trace_id: str = ""
    failed_field: str | None = None
    suggested_action: str = ""
    retryable: bool = False
    checks: tuple[RiskCheck, ...] = field(default_factory=tuple)


# 结果结构只保留一套契约，RiskCheckResult 是 RiskDecision 的别名，方便新旧调用方共用。
RiskCheckResult = RiskDecision


class RiskManager:
    """Mandatory gate before any order intent reaches the executor."""

    def check_order_intent(
        self,
        intent: OrderIntent,
        *,
        market: Market | None = None,
        orderbook: OrderbookSnapshot | None = None,
        position: Position | None = None,
        open_orders: Iterable[Order] = (),
        allocation_plan: AllocationPlan | None = None,
        classification_passed: bool | None = None,
        classification_reason: str | None = None,
        market_active: bool | None = None,
        market_open: bool | None = None,
        clob_enabled: bool | None = None,
        resolved: bool | None = None,
        cancelled: bool | None = None,
        archived: bool | None = None,
        geoblocked: bool = False,
        balance_usdc: Decimal | None = None,
        allowance_usdc: Decimal | None = None,
        portfolio_total_invested_usdc: Decimal | None = None,
        open_orders_count: int | None = None,
        retry_count: int = 0,
        order_retry_limit: int | None = None,
        entry_no_price_max: Decimal = Decimal("0.60"),
        max_order_usdc: Decimal | None = None,
        max_market_usdc: Decimal | None = None,
        max_total_usdc: Decimal | None = None,
        max_open_orders: int | None = None,
        min_order_size: Decimal | None = None,
        min_liquidity_usdc: Decimal | None = None,
        max_spread: Decimal | None = None,
    ) -> RiskCheckResult:
        # 这里只读本地快照和热状态；P0 路径不允许为了下单临时打 REST 或查数据库。
        open_orders = tuple(open_orders)
        if portfolio_total_invested_usdc is None and allocation_plan is not None:
            # allocation plan 里通常已经包含当前待审查 intent 的预算；这里要扣掉它，避免总仓检查重复计数。
            portfolio_total_invested_usdc = allocation_plan.allocated_budget_usdc - _intent_notional_usdc(
                intent
            )
        if portfolio_total_invested_usdc is None:
            portfolio_total_invested_usdc = Decimal("0")
        if portfolio_total_invested_usdc < Decimal("0"):
            portfolio_total_invested_usdc = Decimal("0")
        if open_orders_count is None:
            open_orders_count = len(open_orders)

        checks: list[RiskCheck] = []

        notional_usdc = _intent_notional_usdc(intent)
        if notional_usdc <= Decimal("0"):
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="order_size_gate",
                reason="missing_order_size",
                field="intent.amount_usdc",
                suggested_action="reject",
                retryable=False,
            )

        checks.append(
            RiskCheck(
                name="order_size_gate",
                passed=True,
                field=(
                    "intent.amount_usdc"
                    if intent.amount_usdc is not None
                    else "intent.size_shares"
                ),
                value=notional_usdc,
            )
        )

        if classification_passed is False:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="classification_gate",
                reason=classification_reason or "market_out_of_universe",
                field="classification",
                suggested_action="reject",
                retryable=False,
            )
        checks.append(
            RiskCheck(
                name="classification_gate",
                passed=True,
                field="classification",
                value=classification_passed if classification_passed is not None else True,
            )
        )

        (
            market_active,
            market_open,
            clob_enabled,
            resolved,
            cancelled,
            archived,
        ) = _resolve_market_flags(
            market=market,
            market_active=market_active,
            market_open=market_open,
            clob_enabled=clob_enabled,
            resolved=resolved,
            cancelled=cancelled,
            archived=archived,
        )

        # 这些是强制门禁：市场状态不对时，下单只会把错误状态继续放大，必须在本地直接拦住。
        for name, passed, reason, field_name, suggested_action in (
            (
                "market_active_gate",
                market_active,
                "market_not_active",
                "market.active",
                "refresh_snapshot",
            ),
            (
                "market_open_gate",
                market_open,
                "market_not_open",
                "market.open",
                "refresh_snapshot",
            ),
            (
                "clob_gate",
                clob_enabled,
                "clob_disabled",
                "market.clob_enabled",
                "refresh_snapshot",
            ),
            ("resolved_gate", not resolved, "market_resolved", "market.resolved", "reject"),
            ("cancelled_gate", not cancelled, "market_cancelled", "market.cancelled", "reject"),
            ("archived_gate", not archived, "market_archived", "market.archived", "reject"),
        ):
            checks.append(RiskCheck(name=name, passed=bool(passed), field=field_name, value=passed))
            if not passed:
                return self._fail(
                    trace_id=intent.trace_id,
                    checks=checks,
                    name=name,
                    reason=reason,
                    field=field_name,
                    suggested_action=suggested_action,
                    retryable=False,
                )

        if market is not None and market.trading_status != TradingStatus.ELIGIBLE:
            # 分类和状态都必须在本地快照里满足；CANDIDATE/PAUSED/CLOSED 继续下单只会制造无效风控流量。
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="market_status_gate",
                reason="market_not_active",
                field="market.trading_status",
                value=market.trading_status,
                suggested_action="reject",
                retryable=False,
            )

        if intent.price <= Decimal("0"):
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="price_gate",
                reason="price_invalid",
                field="intent.price",
                value=intent.price,
                suggested_action="reject",
                retryable=False,
            )

        if intent.side == OrderSide.BUY and intent.price > entry_no_price_max:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="price_gate",
                reason="price_above_entry_max",
                field="intent.price",
                value=intent.price,
                suggested_action="reject",
                retryable=False,
            )

        tick_size = _effective_tick_size(market=market, orderbook=orderbook)
        if tick_size is not None:
            if tick_size <= Decimal("0") or not _is_multiple_of_tick(intent.price, tick_size):
                return self._fail(
                    trace_id=intent.trace_id,
                    checks=checks,
                    name="tick_size_gate",
                    reason="tick_size_invalid",
                    field="intent.price",
                    value={"price": intent.price, "tick_size": tick_size},
                    suggested_action="reject",
                    retryable=False,
                )
        checks.append(
            RiskCheck(
                name="tick_size_gate",
                passed=True,
                field="intent.price",
                value={"price": intent.price, "tick_size": tick_size},
            )
        )

        if market is not None:
            market_min_order_size = market.min_order_size
        else:
            market_min_order_size = min_order_size
        if market_min_order_size is None:
            market_min_order_size = Decimal("0")
        if min_order_size is not None and market_min_order_size < min_order_size:
            market_min_order_size = min_order_size

        if notional_usdc < market_min_order_size:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="min_order_gate",
                reason="min_order_not_met",
                field="intent.amount_usdc",
                value={"notional_usdc": notional_usdc, "min_order_size": market_min_order_size},
                suggested_action="reject",
                retryable=False,
            )

        market_exposure_usdc = current_exposure_usdc(
            position,
            _filter_open_orders_for_subject(open_orders, intent),
        )
        if max_order_usdc is not None and notional_usdc > max_order_usdc:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="single_order_gate",
                reason="single_order_limit_reached",
                field="intent.amount_usdc",
                value={"notional_usdc": notional_usdc, "max_order_usdc": max_order_usdc},
                suggested_action="reduce_size",
                retryable=False,
            )
        if (
            max_market_usdc is not None
            and market_exposure_usdc + notional_usdc > max_market_usdc
        ):
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="single_market_gate",
                reason="market_limit_reached",
                field="market.exposure_usdc",
                value={
                    "exposure_usdc": market_exposure_usdc,
                    "notional_usdc": notional_usdc,
                    "max_market_usdc": max_market_usdc,
                },
                suggested_action="reduce_size",
                retryable=False,
            )
        if (
            max_total_usdc is not None
            and portfolio_total_invested_usdc + notional_usdc > max_total_usdc
        ):
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="total_limit_gate",
                reason="total_limit_reached",
                field="portfolio.total_invested_usdc",
                value={
                    "portfolio_total_invested_usdc": portfolio_total_invested_usdc,
                    "notional_usdc": notional_usdc,
                    "max_total_usdc": max_total_usdc,
                },
                suggested_action="reduce_size",
                retryable=False,
            )

        if max_open_orders is not None and open_orders_count >= max_open_orders:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="open_orders_gate",
                reason="open_orders_limit_reached",
                field="open_orders_count",
                value={"open_orders_count": open_orders_count, "max_open_orders": max_open_orders},
                suggested_action="cancel_open_orders",
                retryable=False,
            )

        if retry_count >= 0 and order_retry_limit is not None and retry_count >= order_retry_limit:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="retry_gate",
                reason="retry_limit_reached",
                field="retry_count",
                value={"retry_count": retry_count, "order_retry_limit": order_retry_limit},
                suggested_action="wait",
                retryable=False,
            )

        if geoblocked:
            # 地理限制、allowance 和余额都来自本地已同步状态；这些信息不需要，也不应该在 P0 路径临时去查慢源。
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="geoblock_gate",
                reason="geoblock_restricted",
                field="account.geoblocked",
                value=True,
                suggested_action="reject",
                retryable=False,
            )
        if balance_usdc is not None and notional_usdc > balance_usdc:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="balance_gate",
                reason="balance_insufficient",
                field="account.balance_usdc",
                value={"balance_usdc": balance_usdc, "notional_usdc": notional_usdc},
                suggested_action="reduce_size",
                retryable=False,
            )
        if allowance_usdc is not None and notional_usdc > allowance_usdc:
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="allowance_gate",
                reason="allowance_insufficient",
                field="account.allowance_usdc",
                value={"allowance_usdc": allowance_usdc, "notional_usdc": notional_usdc},
                suggested_action="approve_or_reduce",
                retryable=False,
            )

        if orderbook is not None:
            spread = orderbook.spread
            if max_spread is not None and spread is not None and spread > max_spread:
                return self._fail(
                    trace_id=intent.trace_id,
                    checks=checks,
                    name="spread_gate",
                    reason="spread_too_wide",
                    field="orderbook.spread",
                    value={"spread": spread, "max_spread": max_spread},
                    suggested_action="wait",
                    retryable=True,
                )

            depth_usdc = _orderbook_depth_usdc(orderbook, price_cap=intent.price)
            if min_liquidity_usdc is not None and depth_usdc < min_liquidity_usdc:
                return self._fail(
                    trace_id=intent.trace_id,
                    checks=checks,
                    name="liquidity_gate",
                    reason="liquidity_insufficient",
                    field="orderbook.depth_usdc",
                    value={"depth_usdc": depth_usdc, "min_liquidity_usdc": min_liquidity_usdc},
                    suggested_action="wait",
                    retryable=True,
                )
            if depth_usdc < notional_usdc:
                return self._fail(
                    trace_id=intent.trace_id,
                    checks=checks,
                    name="liquidity_gate",
                    reason="liquidity_insufficient",
                    field="orderbook.depth_usdc",
                    value={"depth_usdc": depth_usdc, "notional_usdc": notional_usdc},
                    suggested_action="wait",
                    retryable=True,
                )

        open_buy_orders = _open_buy_orders_for_subject(open_orders, intent)
        if open_buy_orders:
            # open BUY 长时间挂着说明买入侧状态已经偏离了预期，继续叠单会让仓位和审计都更难解释，必须先 cancel。
            return self._fail(
                trace_id=intent.trace_id,
                checks=checks,
                name="open_buy_gate",
                reason="open_buy_detected",
                field="open_orders.buy",
                value=[
                    order.order_id or order.idempotency_key or order.token_id
                    for order in open_buy_orders
                ],
                suggested_action="cancel_open_buy",
                retryable=False,
            )

        checks.append(
            RiskCheck(
                name="open_buy_gate",
                passed=True,
                field="open_orders.buy",
                value=0,
            )
        )

        return RiskCheckResult(
            trace_id=intent.trace_id,
            passed=True,
            reason="passed",
            suggested_action="submit",
            retryable=False,
            checks=tuple(checks),
        )

    def _fail(
        self,
        *,
        trace_id: str,
        checks: list[RiskCheck],
        name: str,
        reason: str,
        field: str | None,
        suggested_action: str,
        retryable: bool,
        value: object | None = None,
    ) -> RiskCheckResult:
        checks.append(
            RiskCheck(
                name=name,
                passed=False,
                reason=reason,
                field=field,
                value=value,
                suggested_action=suggested_action,
                retryable=retryable,
            )
        )
        return RiskCheckResult(
            trace_id=trace_id,
            passed=False,
            reason=reason,
            failed_field=field,
            suggested_action=suggested_action,
            retryable=retryable,
            checks=tuple(checks),
        )


def _intent_notional_usdc(intent: OrderIntent) -> Decimal:
    if intent.notional_usdc is not None:
        return intent.notional_usdc
    if intent.amount_usdc is not None:
        return intent.amount_usdc
    if intent.size_shares is not None:
        return intent.price * intent.size_shares
    return Decimal("0")


def _resolve_market_flags(
    *,
    market: Market | None,
    market_active: bool | None,
    market_open: bool | None,
    clob_enabled: bool | None,
    resolved: bool | None,
    cancelled: bool | None,
    archived: bool | None,
) -> tuple[bool, bool, bool, bool, bool, bool]:
    if market is not None:
        if market_active is None:
            market_active = market.trading_status == TradingStatus.ELIGIBLE
        if market_open is None:
            market_open = market.trading_status == TradingStatus.ELIGIBLE
        if resolved is None:
            resolved = market.trading_status == TradingStatus.RESOLVED
    market_active = True if market_active is None else market_active
    market_open = True if market_open is None else market_open
    clob_enabled = True if clob_enabled is None else clob_enabled
    resolved = False if resolved is None else resolved
    cancelled = False if cancelled is None else cancelled
    archived = False if archived is None else archived
    return market_active, market_open, clob_enabled, resolved, cancelled, archived
def _effective_tick_size(
    *,
    market: Market | None,
    orderbook: OrderbookSnapshot | None,
) -> Decimal | None:
    if orderbook is not None and orderbook.tick_size is not None:
        return orderbook.tick_size
    if market is not None:
        return market.tick_size
    return None


def _is_multiple_of_tick(price: Decimal, tick_size: Decimal) -> bool:
    if tick_size <= Decimal("0"):
        return False
    remainder = price % tick_size
    return remainder == Decimal("0")


def _orderbook_depth_usdc(orderbook: OrderbookSnapshot, *, price_cap: Decimal) -> Decimal:
    depth_usdc = Decimal("0")
    for level in orderbook.asks:
        if level.price <= price_cap:
            depth_usdc += level.price * level.size
    if (
        depth_usdc == Decimal("0")
        and orderbook.best_ask is not None
        and orderbook.best_ask_size is not None
    ):
        if orderbook.best_ask <= price_cap:
            return orderbook.best_ask * orderbook.best_ask_size
    return depth_usdc


def _filter_open_orders_for_subject(
    open_orders: tuple[Order, ...],
    intent: OrderIntent,
) -> tuple[Order, ...]:
    subject_orders: list[Order] = []
    for order in open_orders:
        if order.condition_id != intent.condition_id:
            continue
        if order.token_id != intent.token_id:
            continue
        subject_orders.append(order)
    return tuple(subject_orders)


def _open_buy_orders_for_subject(
    open_orders: tuple[Order, ...],
    intent: OrderIntent,
) -> tuple[Order, ...]:
    subject_orders: list[Order] = []
    for order in open_orders:
        if order.condition_id != intent.condition_id:
            continue
        if order.token_id != intent.token_id:
            continue
        if order.side != OrderSide.BUY:
            continue
        if order.status in {
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
            OrderStatus.NO_FILL,
            OrderStatus.MATCHED,
        }:
            continue
        subject_orders.append(order)
    return tuple(subject_orders)
