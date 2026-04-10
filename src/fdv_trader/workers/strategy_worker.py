from __future__ import annotations


class StrategyWorker:
    priority = "P0"

    async def run(self) -> None:
        raise NotImplementedError("Strategy worker is not implemented yet.")

