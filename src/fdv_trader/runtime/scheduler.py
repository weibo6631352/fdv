from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


class Scheduler:
    def create_task(self, job: Callable[[], Awaitable[None]]) -> asyncio.Task[None]:
        return asyncio.create_task(job())

