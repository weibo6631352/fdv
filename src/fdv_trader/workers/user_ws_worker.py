from __future__ import annotations


class UserWsWorker:
    priority = "P0"

    async def run(self) -> None:
        raise NotImplementedError("User WebSocket worker is not implemented yet.")

