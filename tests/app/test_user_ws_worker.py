from __future__ import annotations

import asyncio
from decimal import Decimal

from fdv_trader.domain.events import DomainEventType
from fdv_trader.runtime.account_state import AccountStateStore
from fdv_trader.workers.user_ws_worker import UserWsWorker


def test_user_ws_worker_tracks_balance_position_and_connection_state() -> None:
    async def run() -> None:
        store = AccountStateStore()
        worker = UserWsWorker(account_state_store=store)

        balance_result = await worker.process_message(
            {
                "type": "balance",
                "trace_id": "trace-balance",
                "balance_usdc": "100",
                "allowance_usdc": "90",
            }
        )
        assert balance_result.snapshot.balance_usdc == Decimal("100")
        assert balance_result.snapshot.allowance_usdc == Decimal("90")
        assert balance_result.events[0].event_type == DomainEventType.BALANCE_UPDATED

        position_result = await worker.process_message(
            {
                "type": "position",
                "trace_id": "trace-position",
                "position": {
                    "condition_id": "condition",
                    "token_id": "token",
                    "market_slug": "token-500m-fdv",
                    "shares": "5",
                    "cost_usdc": "3.0",
                },
            }
        )
        position = position_result.snapshot.get_position("condition", "token")
        assert position is not None
        assert position.shares == Decimal("5")
        assert position_result.events[0].event_type == DomainEventType.POSITION_UPDATED

        disconnected = await worker.set_connection_state(False, trace_id="trace-disconnect")
        assert disconnected.snapshot.allow_new_buys is False

        reconnected = await worker.set_connection_state(True, trace_id="trace-reconnect")
        assert reconnected.snapshot.user_ws_connected is True
        assert reconnected.snapshot.allow_new_buys is False

    asyncio.run(run())


def test_user_ws_worker_requires_reconcile_after_reconnect_before_buying_resumes() -> None:
    async def run() -> None:
        store = AccountStateStore()
        worker = UserWsWorker(account_state_store=store)

        await worker.set_connection_state(False, trace_id="trace-disconnect")
        assert store.snapshot().allow_new_buys is False

        await worker.set_connection_state(True, trace_id="trace-reconnect")
        assert store.snapshot().user_ws_connected is True
        assert store.snapshot().allow_new_buys is False
        assert store.snapshot().last_reconcile_at is None

        store.mark_reconciled()
        assert store.snapshot().last_reconcile_at is not None
        assert store.snapshot().allow_new_buys is True

    asyncio.run(run())
