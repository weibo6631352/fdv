from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from fdv_trader.domain.allocation import AllocationPlan
from fdv_trader.domain.market import Market
from fdv_trader.domain.order import Order, OrderIntent
from fdv_trader.domain.orderbook import OrderbookSnapshot
from fdv_trader.domain.position import Position
from fdv_trader.domain.risk import RiskCheckResult, RiskManager


class TradingService:
    """Coordinates risk-checked order intents and execution."""

    def __init__(
        self,
        *,
        risk_manager: RiskManager | None = None,
        executor: object | None = None,
    ) -> None:
        self._risk_manager = risk_manager or RiskManager()
        self._executor = executor

    async def review_intent(
        self,
        intent: OrderIntent,
        *,
        market: Market | None = None,
        orderbook: OrderbookSnapshot | None = None,
        position: Position | None = None,
        open_orders: Iterable[Order] = (),
        allocation_plan: AllocationPlan | None = None,
        classification_passed: bool | None = True,
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
    ) -> "TradingReviewResult":
        risk_decision = self._risk_manager.check_order_intent(
            intent,
            market=market,
            orderbook=orderbook,
            position=position,
            open_orders=open_orders,
            allocation_plan=allocation_plan,
            classification_passed=classification_passed,
            classification_reason=classification_reason,
            market_active=market_active,
            market_open=market_open,
            clob_enabled=clob_enabled,
            resolved=resolved,
            cancelled=cancelled,
            archived=archived,
            geoblocked=geoblocked,
            balance_usdc=balance_usdc,
            allowance_usdc=allowance_usdc,
            portfolio_total_invested_usdc=portfolio_total_invested_usdc,
            open_orders_count=open_orders_count,
            retry_count=retry_count,
            order_retry_limit=order_retry_limit,
            entry_no_price_max=entry_no_price_max,
            max_order_usdc=max_order_usdc,
            max_market_usdc=max_market_usdc,
            max_total_usdc=max_total_usdc,
            max_open_orders=max_open_orders,
            min_order_size=min_order_size,
            min_liquidity_usdc=min_liquidity_usdc,
            max_spread=max_spread,
        )
        submitted = False
        submission_error: str | None = None
        if risk_decision.passed and self._executor is not None:
            try:
                result = self._executor.submit(intent)
                if hasattr(result, "__await__"):
                    await result
                submitted = True
            except Exception as exc:  # pragma: no cover - injected in tests
                submission_error = str(exc)
        return TradingReviewResult(
            intent=intent,
            risk_decision=risk_decision,
            submitted=submitted,
            submission_error=submission_error,
        )


@dataclass(frozen=True, slots=True)
class TradingReviewResult:
    intent: OrderIntent
    risk_decision: RiskCheckResult
    submitted: bool
    submission_error: str | None = None
