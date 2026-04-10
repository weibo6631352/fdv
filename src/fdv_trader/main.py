from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from fdv_trader.app.market_service import MarketService
from fdv_trader.app.reconcile_service import ReconcileService
from fdv_trader.app.strategy_service import StrategyService
from fdv_trader.app.trading_service import TradingService
from fdv_trader.config import Settings, StartupReadiness, load_settings
from fdv_trader.infra.db import DatabasePersistenceRepository, build_session_factory
from fdv_trader.infra.outbox.local_queue import LocalOutbox
from fdv_trader.infra.polymarket import (
    ClobClient,
    DataClient,
    GammaClient,
    PolymarketOrderExecutionClient,
    PolymarketTradingClient,
    PolymarketWebSocketClient,
    build_trading_client,
)
from fdv_trader.infra.polymarket.order_executor import (
    InMemoryPolymarketOrderClient,
    PolymarketOrderExecutor,
)
from fdv_trader.logging import configure_logging
from fdv_trader.runtime.account_state import AccountStateStore
from fdv_trader.runtime.event_bus import EventBus
from fdv_trader.runtime.registry import MarketRegistry
from fdv_trader.workers.market_discovery_worker import MarketDiscoveryWorker
from fdv_trader.workers.market_ws_worker import MarketWsWorker
from fdv_trader.workers.persistence_worker import PersistenceWorker
from fdv_trader.workers.reconcile_worker import ReconcileWorker
from fdv_trader.workers.strategy_worker import StrategyWorker
from fdv_trader.workers.user_ws_worker import UserWsWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeComponents:
    settings: Settings
    readiness: StartupReadiness
    gamma_client: GammaClient
    clob_client: ClobClient
    data_client: DataClient
    trading_client: PolymarketTradingClient | None
    polymarket_ws_client: PolymarketWebSocketClient
    event_bus: EventBus
    registry: MarketRegistry
    outbox: LocalOutbox
    db_session_factory: object
    persistence_repository: DatabasePersistenceRepository
    persistence_worker: PersistenceWorker
    account_state_store: AccountStateStore
    order_executor: PolymarketOrderExecutor
    market_ws_worker: MarketWsWorker
    user_ws_worker: UserWsWorker
    market_service: MarketService
    market_discovery_worker: MarketDiscoveryWorker
    strategy_service: StrategyService
    trading_service: TradingService
    strategy_worker: StrategyWorker
    reconcile_service: ReconcileService
    reconcile_worker: ReconcileWorker


def build_runtime(settings: Settings | None = None) -> RuntimeComponents:
    settings = settings or load_settings()
    readiness = settings.validate_startup_readiness()
    trading_client = build_trading_client(settings)
    gamma_client = GammaClient(base_url=settings.polymarket_gamma_host)
    clob_client = ClobClient(
        base_url=settings.polymarket_clob_host,
        auth_client=trading_client,
    )
    data_client = DataClient(
        base_url=settings.polymarket_data_host,
        auth_client=trading_client,
    )
    polymarket_ws_client = PolymarketWebSocketClient(
        market_url=settings.polymarket_market_ws,
        user_url=settings.polymarket_user_ws,
    )
    event_bus = EventBus(
        trading_capacity=settings.trading_event_queue_max_size,
        maintenance_capacity=settings.maintenance_event_queue_max_size,
        persistence_capacity=settings.persistence_event_queue_max_size,
    )
    registry = MarketRegistry()
    outbox = LocalOutbox(max_size=settings.persistence_event_queue_max_size)
    db_session_factory = build_session_factory(settings.database_url)
    persistence_repository = DatabasePersistenceRepository(db_session_factory)
    persistence_worker = PersistenceWorker(
        outbox=outbox,
        repository=persistence_repository,
    )
    account_state_store = AccountStateStore()
    account_state_store.update_balances(
        balance_usdc=settings.portfolio_budget_usdc,
        allowance_usdc=settings.portfolio_budget_usdc,
    )
    execution_client = (
        PolymarketOrderExecutionClient(trading_client)
        if trading_client is not None
        else InMemoryPolymarketOrderClient()
    )
    order_executor = PolymarketOrderExecutor(
        client=execution_client,
        outbox=outbox,
        sign_timeout_ms=settings.order_sign_timeout_ms,
        submit_timeout_ms=settings.order_submit_timeout_ms,
        critical_lock_timeout_ms=settings.critical_lock_timeout_ms,
    )

    async def load_market_rest_snapshot(token_id: str):
        orderbook = await clob_client.get_orderbook(token_id)
        return orderbook.to_snapshot()

    market_ws_worker = MarketWsWorker(
        event_bus=event_bus,
        registry=registry,
        entry_price_max=settings.entry_no_price_max,
        rest_snapshot_loader=load_market_rest_snapshot,
    )
    market_service = MarketService(
        registry=registry,
        market_tracker=market_ws_worker,
    )
    strategy_service = StrategyService(
        registry=registry,
        orderbook_reader=market_ws_worker.snapshot,
    )
    trading_service = TradingService(executor=order_executor)
    user_ws_worker = UserWsWorker(
        event_bus=event_bus,
        account_state_store=account_state_store,
    )
    strategy_worker = StrategyWorker(
        event_bus=event_bus,
        strategy_service=strategy_service,
        trading_service=trading_service,
        account_state_store=account_state_store,
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
    reconcile_service = ReconcileService()
    reconcile_worker = ReconcileWorker(
        event_bus=event_bus,
        reconcile_service=reconcile_service,
        registry_snapshot_provider=registry.snapshot,
        account_state_store=account_state_store,
        trading_service=trading_service,
        executor=order_executor,
        registry=registry,
        market_ws_worker=market_ws_worker,
        gamma_client=gamma_client,
        clob_client=clob_client,
        data_client=data_client,
        trading_client=trading_client,
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
        gamma_client=gamma_client,
        clob_client=clob_client,
        data_client=data_client,
        trading_client=trading_client,
        polymarket_ws_client=polymarket_ws_client,
        event_bus=event_bus,
        registry=registry,
        outbox=outbox,
        db_session_factory=db_session_factory,
        persistence_repository=persistence_repository,
        persistence_worker=persistence_worker,
        account_state_store=account_state_store,
        order_executor=order_executor,
        market_ws_worker=market_ws_worker,
        user_ws_worker=user_ws_worker,
        market_service=market_service,
        market_discovery_worker=market_discovery_worker,
        strategy_service=strategy_service,
        trading_service=trading_service,
        strategy_worker=strategy_worker,
        reconcile_service=reconcile_service,
        reconcile_worker=reconcile_worker,
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
