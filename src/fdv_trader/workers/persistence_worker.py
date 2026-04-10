from __future__ import annotations


class PersistenceWorker:
    priority = "P3"

    async def run(self) -> None:
        raise NotImplementedError("Persistence worker is not implemented yet.")

