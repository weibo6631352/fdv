from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_type: str
    trace_id: str
    payload: Mapping[str, Any]
    created_at: datetime
    idempotency_key: str


class LocalOutbox:
    def __init__(self, max_size: int) -> None:
        self._queue: asyncio.Queue[OutboxEvent] = asyncio.Queue(maxsize=max_size)

    async def put(self, event: OutboxEvent) -> None:
        await self._queue.put(event)

    async def get(self) -> OutboxEvent:
        return await self._queue.get()

