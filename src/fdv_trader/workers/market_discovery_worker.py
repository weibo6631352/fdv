from __future__ import annotations


class MarketDiscoveryWorker:
    priority = "P2"

    async def run(self) -> None:
        raise NotImplementedError("Market discovery worker is not implemented yet.")

