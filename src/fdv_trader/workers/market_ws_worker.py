from __future__ import annotations


class MarketWsWorker:
    priority = "P0"

    async def run(self) -> None:
        raise NotImplementedError("Market WebSocket worker is not implemented yet.")

