from __future__ import annotations

import asyncio
from decimal import Decimal

from fdv_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from fdv_trader.config import Settings
from fdv_trader.main import build_runtime


def test_build_runtime_wires_m2_components() -> None:
    runtime = build_runtime(
        Settings(
            portfolio_budget_usdc=Decimal("100"),
            max_order_usdc=Decimal("25"),
            max_market_usdc=Decimal("50"),
            max_total_usdc=Decimal("100"),
            min_liquidity_usdc=Decimal("5"),
            max_spread=Decimal("0.10"),
            max_open_orders=10,
        )
    )

    assert runtime.market_discovery_worker is not None
    assert runtime.market_service is not None
    assert runtime.market_ws_worker is not None
    assert runtime.user_ws_worker is not None
    assert runtime.strategy_service is not None
    assert runtime.trading_service is not None
    assert runtime.strategy_worker is not None
    assert runtime.account_state_store is not None
    assert runtime.account_state_store.snapshot().user_ws_connected is False
    assert runtime.account_state_store.snapshot().allow_new_buys is False
    assert runtime.account_state_store.snapshot().last_reconcile_at is None
    assert runtime.order_executor is not None
    assert runtime.reconcile_service is not None
    assert runtime.reconcile_worker is not None
    assert runtime.strategy_worker.priority == "P0"


def test_build_runtime_binds_market_event_outbox_sink() -> None:
    async def run() -> None:
        runtime = build_runtime(
            Settings(
                portfolio_budget_usdc=Decimal("100"),
                max_order_usdc=Decimal("25"),
                max_market_usdc=Decimal("50"),
                max_total_usdc=Decimal("100"),
                min_liquidity_usdc=Decimal("5"),
                max_spread=Decimal("0.10"),
                max_open_orders=10,
            )
        )

        event = DomainEvent(
            trace_id="trace-market",
            event_type=DomainEventType.MARKET_UPDATED,
            event_id="event-market",
            market_slug="token-500m-fdv",
            condition_id="condition-500m",
            token_id="no-token-500m",
            reason="market_snapshot",
            payload={"market": {"condition_id": "condition-500m"}},
        )
        await runtime.event_bus.publish(OutboxPriority.P2, event)

        queued = await asyncio.wait_for(runtime.outbox.get(), timeout=0.1)
        assert queued.event_id == event.event_id
        assert queued.event_type == DomainEventType.MARKET_UPDATED.value
        assert queued.payload["market"]["condition_id"] == "condition-500m"

    asyncio.run(run())


def test_build_runtime_binds_user_event_outbox_sink_with_trimmed_payload() -> None:
    async def run() -> None:
        runtime = build_runtime(
            Settings(
                portfolio_budget_usdc=Decimal("100"),
                max_order_usdc=Decimal("25"),
                max_market_usdc=Decimal("50"),
                max_total_usdc=Decimal("100"),
                min_liquidity_usdc=Decimal("5"),
                max_spread=Decimal("0.10"),
                max_open_orders=10,
            )
        )

        event = DomainEvent(
            trace_id="trace-order",
            event_type=DomainEventType.ORDER_STATE_UPDATED,
            event_id="event-order",
            market_slug="token-500m-fdv",
            condition_id="condition-500m",
            token_id="no-token-500m",
            reason="order_update",
            payload={
                "order": {
                    "condition_id": "condition-500m",
                    "token_id": "no-token-500m",
                    "side": "BUY",
                    "order_type": "FAK",
                    "price": "0.60",
                },
                "snapshot": {"positions": []},
            },
        )
        await runtime.event_bus.publish(OutboxPriority.P0, event)

        queued = await asyncio.wait_for(runtime.outbox.get(), timeout=0.1)
        assert queued.event_id == event.event_id
        assert queued.event_type == DomainEventType.ORDER_STATE_UPDATED.value
        assert "order" in queued.payload
        assert "snapshot" not in queued.payload

    asyncio.run(run())


def test_build_runtime_binds_balance_event_outbox_sink() -> None:
    async def run() -> None:
        runtime = build_runtime(
            Settings(
                portfolio_budget_usdc=Decimal("100"),
                max_order_usdc=Decimal("25"),
                max_market_usdc=Decimal("50"),
                max_total_usdc=Decimal("100"),
                min_liquidity_usdc=Decimal("5"),
                max_spread=Decimal("0.10"),
                max_open_orders=10,
            )
        )

        event = DomainEvent(
            trace_id="trace-balance",
            event_type=DomainEventType.BALANCE_UPDATED,
            event_id="event-balance",
            reason="balance_update",
            payload={
                "balance_usdc": "120",
                "allowance_usdc": "90",
                "user_ws_connected": True,
                "allow_new_buys": True,
            },
        )
        await runtime.event_bus.publish(OutboxPriority.P0, event)

        queued = await asyncio.wait_for(runtime.outbox.get(), timeout=0.1)
        assert queued.event_id == event.event_id
        assert queued.event_type == DomainEventType.BALANCE_UPDATED.value
        assert str(queued.payload["balance_usdc"]) == "120"
        assert str(queued.payload["allowance_usdc"]) == "90"

    asyncio.run(run())
