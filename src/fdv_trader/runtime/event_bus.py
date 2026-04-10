from __future__ import annotations

import asyncio
from itertools import count
from typing import Any


class EventBus:
    def __init__(self, max_size: int) -> None:
        self._sequence = count()
        self._queue: asyncio.PriorityQueue[tuple[int, int, Any]] = asyncio.PriorityQueue(maxsize=max_size)

    async def publish(self, priority: int, event: Any) -> None:
        await self._queue.put((priority, next(self._sequence), event))

    async def next_event(self) -> Any:
        _, _, event = await self._queue.get()
        return event

