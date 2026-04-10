from __future__ import annotations

import asyncio

from fdv_trader.logging import configure_logging


async def run() -> None:
    configure_logging()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()

