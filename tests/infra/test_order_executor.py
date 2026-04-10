from __future__ import annotations

import asyncio
from decimal import Decimal

from fdv_trader.domain.order import BuyOrderIntent, OrderResultStatus
from fdv_trader.infra.outbox.local_queue import LocalOutbox
from fdv_trader.infra.polymarket.order_executor import (
    InMemoryPolymarketOrderClient,
    PolymarketOrderExecutor,
)


def test_order_executor_records_outbox_before_returning_result() -> None:
    async def run() -> None:
        outbox = LocalOutbox(max_size=32)
        executor = PolymarketOrderExecutor(
            client=InMemoryPolymarketOrderClient(),
            outbox=outbox,
        )

        result = await executor.submit(
            BuyOrderIntent(
                trace_id="trace",
                condition_id="condition",
                token_id="token",
                market_slug="token-500m-fdv",
                price=Decimal("0.60"),
                amount_usdc=Decimal("10"),
            )
        )

        assert result.status == OrderResultStatus.NO_FILL
        event = await outbox.get()
        assert event.event_type == "order_created"

    asyncio.run(run())
