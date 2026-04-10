from __future__ import annotations

from fdv_trader.infra.outbox.local_queue import LocalOutbox


class OutboxWorker:
    def __init__(self, outbox: LocalOutbox) -> None:
        self._outbox = outbox

    async def run_once(self) -> None:
        await self._outbox.get()

