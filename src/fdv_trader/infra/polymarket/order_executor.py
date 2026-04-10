from __future__ import annotations

from fdv_trader.domain.order import OrderIntent


class PolymarketOrderExecutor:
    """Only adapter allowed to submit, cancel, or replace Polymarket orders."""

    async def submit(self, intent: OrderIntent) -> None:
        raise NotImplementedError("Polymarket order submission is not implemented yet.")

