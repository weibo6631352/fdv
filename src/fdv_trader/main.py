from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from fdv_trader.app.market_service import MarketService
from fdv_trader.app.strategy_service import StrategyService
from fdv_trader.app.trading_service import TradingService
from fdv_trader.config import Settings, StartupReadiness, load_settings
from fdv_trader.logging import configure_logging
from fdv_trader.runtime.event_bus import EventBus
from fdv_trader.runtime.registry import MarketRegistry
from fdv_trader.workers.market_discovery_worker import MarketDiscoveryWorker
from fdv_trader.workers.market_ws_worker import MarketWsWorker
from fdv_trader.workers.strategy_worker import StrategyWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    settings: Settings
    readiness: StartupReadiness
    event_bus: EventBus
    registry: MarketRegistry
    market_ws_worker: MarketWsWorker
    market_service: MarketService
    market_discovery_worker: MarketDiscoveryWorker
    strategy_service: StrategyService
    trading_service: TradingService
    strategy_worker: StrategyWorker


def build_runtime(settings: Settings | None = None) -> RuntimeComponents:
    settings = settings or load_settings()
    readiness = settings.validate_startup_readiness()
    event_bus = EventBus(
        trading_capacity=settings.trading_event_queue_max_size,
        maintenance_capacity=settings.maintenance_event_queue_max_size,
        persistence_capacity=settings.persistence_event_queue_max_size,
    )
    registry = MarketRegistry()
    market_ws_worker = MarketWsWorker(
        event_bus=event_bus,
        registry=registry,
        entry_price_max=settings.entry_no_price_max,
    )
    market_service = MarketService(
        registry=registry,
        market_tracker=market_ws_worker,
    )
    strategy_service = StrategyService(
        registry=registry,
        orderbook_reader=market_ws_worker.snapshot,
    )
    trading_service = TradingService()
    strategy_worker = StrategyWorker(
        event_bus=event_bus,
        strategy_service=strategy_service,
        trading_service=trading_service,
        portfolio_budget_usdc=settings.portfolio_budget_usdc,
        available_usdc=settings.portfolio_budget_usdc,
        max_order_usdc=settings.max_order_usdc,
        max_market_usdc=settings.max_market_usdc,
        max_total_usdc=settings.max_total_usdc,
        entry_no_price_max=settings.entry_no_price_max,
        min_liquidity_usdc=settings.min_liquidity_usdc,
        max_spread=settings.max_spread,
        max_open_orders=settings.max_open_orders,
        order_retry_limit=settings.order_retry_limit,
    )
    market_discovery_worker = MarketDiscoveryWorker(
        market_service=market_service,
        event_bus=event_bus,
        registry=registry,
        market_tracker=market_ws_worker,
    )
    return RuntimeComponents(
        settings=settings,
        readiness=readiness,
        event_bus=event_bus,
        registry=registry,
        market_ws_worker=market_ws_worker,
        market_service=market_service,
        market_discovery_worker=market_discovery_worker,
        strategy_service=strategy_service,
        trading_service=trading_service,
        strategy_worker=strategy_worker,
    )


async def run() -> RuntimeComponents:
    configure_logging()
    runtime = build_runtime()
    if not runtime.readiness.ready_to_trade:
        logger.warning(
            "runtime built in safe mode; automatic trading remains disabled",
            extra={"readiness": runtime.readiness.as_dict()},
        )
    return runtime


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
