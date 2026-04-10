from __future__ import annotations

import asyncio
from decimal import Decimal

from fdv_trader.app.reconcile_service import ReconcileActionType, ReconcileService
from fdv_trader.app.trading_service import TradingService
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import (
    CancelOrderIntent,
    OrderRecord,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    SellOrderIntent,
)
from fdv_trader.domain.position import Position
from fdv_trader.runtime.account_state import AccountStateStore
from fdv_trader.runtime.registry import MarketRegistry
from fdv_trader.workers.reconcile_worker import ReconcileWorker


class _StubExecutor:
    async def submit(self, intent: SellOrderIntent) -> OrderResult:
        return OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.LIVE,
            intent=intent,
            side=intent.side,
            order_type=intent.order_type,
            price=intent.price,
            requested_size_shares=intent.size_shares,
            notional_usdc=intent.notional_usdc,
            reason="sell_submitted",
        )

    async def cancel(self, intent: CancelOrderIntent) -> OrderResult:
        return OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.CANCELLED,
            intent=intent,
            reason="cancelled",
        )


def test_reconcile_worker_cancels_open_buy_and_backfills_missing_sell() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        market = Market(
            condition_id="condition",
            market_slug="token-500m-fdv",
            no_token_id="token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            category="Crypto",
            matched_keywords=("crypto", "fdv", "500m"),
            trading_status=TradingStatus.ELIGIBLE,
        )
        registry.upsert(market)

        account_state_store = AccountStateStore()
        account_state_store.upsert_position(
            Position(
                condition_id="condition",
                token_id="token",
                market_slug=market.market_slug,
                shares=Decimal("5"),
                cost_usdc=Decimal("3"),
            )
        )
        account_state_store.upsert_order(
            OrderRecord(
                trace_id="trace-buy",
                condition_id="condition",
                token_id="token",
                market_slug=market.market_slug,
                side=OrderSide.BUY,
                order_type=OrderType.FAK,
                price=Decimal("0.60"),
                amount_usdc=Decimal("3"),
                order_id="buy-1",
                status=OrderStatus.LIVE,
                remaining_shares=Decimal("5"),
                idempotency_key="buy-1",
                reason="open_buy_detected",
            )
        )

        executor = _StubExecutor()
        worker = ReconcileWorker(
            reconcile_service=ReconcileService(),
            registry_snapshot_provider=registry.snapshot,
            account_state_store=account_state_store,
            trading_service=TradingService(executor=executor),
            executor=executor,
        )

        result = await worker.reconcile_once(trace_id="trace-reconcile")

        assert result.plan.has_changes
        action_types = {action.action_type for action in result.plan.market_plans[0].actions}
        assert ReconcileActionType.CANCEL_OPEN_BUY in action_types
        assert ReconcileActionType.SUBMIT_MISSING_SELL in action_types

    asyncio.run(run())
