from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polymarket_trader.app.market_service import MarketService
from polymarket_trader.app.ports import bind_strategy_orderbook_reader, build_strategy_ports
from polymarket_trader.app.reconcile_service import ReconcileService
from polymarket_trader.app.strategy_host import load_strategy
from polymarket_trader.app.strategy_service import StrategyService
from polymarket_trader.app.trading_service import TradingService
from polymarket_trader.config import Settings, StartupReadiness, load_settings
from polymarket_trader.domain.events import DomainEvent, OutboxPriority
from polymarket_trader.infra.db import (
    AccountSnapshotRepository,
    DatabasePersistenceRepository,
    FillRepository,
    MarketRepository,
    OrderRepository,
    PositionRepository,
    build_session_factory,
)
from polymarket_trader.infra.outbox.local_queue import LocalOutbox
from polymarket_trader.infra.outbox import build_domain_event_outbox_sink
from polymarket_trader.infra.polymarket import (
    ClobClient,
    DataClient,
    GammaClient,
    PolymarketOrderExecutionClient,
    PolymarketTradingClient,
    PolymarketWebSocketClient,
    build_trading_client,
)
from polymarket_trader.infra.polymarket.order_executor import (
    InMemoryPolymarketOrderClient,
    PolymarketOrderExecutor,
)
from polymarket_trader.logging import LoggingRuntime, configure_logging
from polymarket_trader.observability.metrics import MetricsRegistry
from polymarket_trader.runtime import RuntimePhase, Scheduler, Supervisor, WorkerLifecycleState
from polymarket_trader.runtime.account_state import AccountStateStore
from polymarket_trader.runtime.event_bus import EventBus
from polymarket_trader.runtime.registry import MarketRegistry
from strategy_sdk import DiscoveryEndpoint, DiscoveryQuery, StrategyModule
from polymarket_trader.workers.market_discovery_worker import MarketDiscoveryWorker
from polymarket_trader.workers.market_ws_worker import MarketWsWorker
from polymarket_trader.workers.persistence_worker import PersistenceWorker
from polymarket_trader.workers.reconcile_worker import ReconcileWorker
from polymarket_trader.workers.strategy_worker import StrategyWorker
from polymarket_trader.workers.user_ws_worker import UserWsWorker

logger = logging.getLogger(__name__)

_MARKET_DISCOVERY_EVENT_PAGE_LIMIT = 50
_MARKET_DISCOVERY_MARKET_BUDGET_PER_TICK = 1000
_MARKET_DISCOVERY_REQUEST_BUDGET_PER_TICK = 2
_MARKET_DISCOVERY_MAX_RUNTIME_MS = 200.0
_MARKET_DISCOVERY_TICK_SECONDS = 0.5
_MARKET_DISCOVERY_RETRY_BACKOFF_SECONDS = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class FullMarketDiscoveryState:
    after_cursor: str | None = None
    round_id: int = 1
    round_started_at: datetime | None = None
    last_round_completed_at: datetime | None = None
    last_completed_round_pages: int = 0
    last_completed_round_markets: int = 0
    last_page_size: int = 0
    pages_scanned_in_round: int = 0
    markets_seen_in_round: int = 0
    last_tick_started_at: datetime | None = None
    last_tick_completed_at: datetime | None = None
    last_tick_requests: int = 0
    last_tick_markets: int = 0
    last_error: str | None = None
    consecutive_failures: int = 0

    def start_tick(self) -> None:
        self.last_tick_started_at = _utc_now()
        self.last_tick_completed_at = None
        self.last_tick_requests = 0
        self.last_tick_markets = 0
        if self.round_started_at is None:
            self.round_started_at = self.last_tick_started_at

    def record_page(self, *, page_size: int, next_cursor: str | None) -> None:
        self.last_page_size = max(0, int(page_size))
        self.pages_scanned_in_round += 1
        self.markets_seen_in_round += max(0, int(page_size))
        self.last_tick_requests += 1
        self.last_tick_markets += max(0, int(page_size))
        self.after_cursor = next_cursor
        self.last_error = None
        self.consecutive_failures = 0

    def finish_round(self) -> None:
        self.after_cursor = None
        self.last_completed_round_pages = self.pages_scanned_in_round
        self.last_completed_round_markets = self.markets_seen_in_round
        self.last_round_completed_at = _utc_now()
        self.round_id += 1
        self.round_started_at = None
        self.pages_scanned_in_round = 0
        self.markets_seen_in_round = 0

    def finish_tick(self) -> None:
        self.last_tick_completed_at = _utc_now()

    def record_failure(self, reason: str) -> None:
        self.last_error = reason
        self.consecutive_failures += 1
        self.finish_tick()


@dataclass(slots=True)
class RuntimeComponents:
    settings: Settings
    readiness: StartupReadiness
    strategy: StrategyModule
    logging_runtime: LoggingRuntime
    gamma_client: GammaClient
    clob_client: ClobClient
    data_client: DataClient
    trading_client: PolymarketTradingClient | None
    polymarket_ws_client: PolymarketWebSocketClient
    event_bus: EventBus
    registry: MarketRegistry
    outbox: LocalOutbox
    db_session_factory: async_sessionmaker[AsyncSession]
    persistence_repository: DatabasePersistenceRepository
    persistence_worker: PersistenceWorker
    account_state_store: AccountStateStore
    order_executor: PolymarketOrderExecutor
    market_ws_worker: MarketWsWorker
    user_ws_worker: UserWsWorker
    market_service: MarketService
    market_discovery_worker: MarketDiscoveryWorker
    market_discovery_scan: FullMarketDiscoveryState
    strategy_service: StrategyService
    trading_service: TradingService
    strategy_worker: StrategyWorker
    reconcile_service: ReconcileService
    reconcile_worker: ReconcileWorker
    scheduler: Scheduler
    supervisor: Supervisor
    metrics: MetricsRegistry
    trading_thread_pool: ThreadPoolExecutor
    maintenance_thread_pool: ThreadPoolExecutor
    maintenance_process_pool: ProcessPoolExecutor
    background_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    admin_service: object | None = None
    bootstrap_summary: dict[str, Any] = field(default_factory=dict)


def build_runtime(settings: Settings | None = None) -> RuntimeComponents:
    settings = settings or load_settings()
    readiness = settings.validate_startup_readiness()
    logging_runtime = configure_logging()
    metrics = MetricsRegistry()
    trading_thread_pool = ThreadPoolExecutor(
        max_workers=settings.trading_worker_threads,
        thread_name_prefix="trader-trading",
    )
    maintenance_thread_pool = ThreadPoolExecutor(
        max_workers=settings.maintenance_worker_threads,
        thread_name_prefix="trader-maintenance",
    )
    maintenance_process_pool = ProcessPoolExecutor(
        max_workers=settings.maintenance_process_workers,
    )
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
    event_bus.bind_persistence_sink(build_domain_event_outbox_sink(outbox))
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
    strategy_ports = build_strategy_ports(
        registry=registry,
        snapshot_provider=account_state_store.snapshot,
    )
    strategy = load_strategy(
        module_path=settings.strategy_module,
        ports=strategy_ports,
        config_path=settings.strategy_config_path,
    )
    profile = strategy.runtime_profile
    execution_client = (
        PolymarketOrderExecutionClient(trading_client)
        if trading_client is not None
        else InMemoryPolymarketOrderClient()
    )
    order_executor = PolymarketOrderExecutor(
        client=execution_client,
        outbox=outbox,
        thread_pool=trading_thread_pool,
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
        entry_price_max=profile.entry_no_price_max,
        rest_snapshot_loader=load_market_rest_snapshot,
    )
    bind_strategy_orderbook_reader(strategy_ports, market_ws_worker.snapshot)
    market_service = MarketService(
        strategy_module=strategy,
        registry=registry,
        market_tracker=market_ws_worker,
        account_snapshot_provider=account_state_store.snapshot,
    )
    strategy_service = StrategyService(
        strategy_module=strategy,
        registry=registry,
        orderbook_reader=market_ws_worker.snapshot,
        runtime_profile=profile,
    )
    trading_service = TradingService(
        executor=order_executor,
        runtime_profile=profile,
    )
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
        max_order_usdc=settings.max_order_usdc,
        max_market_usdc=settings.max_market_usdc,
        max_total_usdc=settings.max_total_usdc,
        max_open_orders=settings.max_open_orders,
        order_retry_limit=settings.order_retry_limit,
    )
    reconcile_service = ReconcileService(strategy_module=strategy)
    reconcile_worker = ReconcileWorker(
        event_bus=event_bus,
        reconcile_service=reconcile_service,
        registry_snapshot_provider=registry.snapshot,
        account_snapshot_provider=account_state_store.snapshot,
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
        retry_delay_seconds=_MARKET_DISCOVERY_RETRY_BACKOFF_SECONDS,
    )
    market_discovery_scan = FullMarketDiscoveryState()
    scheduler = Scheduler()
    supervisor = Supervisor(
        event_bus=event_bus,
        settings_readiness=readiness,
        scheduler_snapshot_provider=scheduler.snapshot,
        account_snapshot_provider=account_state_store.snapshot,
        market_ws_snapshot_provider=market_ws_worker.status_snapshot,
        user_ws_snapshot_provider=user_ws_worker.status_snapshot,
        reconcile_snapshot_provider=reconcile_worker.status_snapshot,
        persistence_snapshot_provider=persistence_worker.snapshot,
        metrics_snapshot_provider=metrics.snapshot,
        trading_queue_warn_depth=settings.trading_queue_warn_depth,
        entry_signal_to_submit_warn_ms=settings.entry_signal_to_submit_warn_ms,
        outbox_depth_warn=settings.persistence_event_queue_max_size,
        reconcile_stale_after_seconds=max(settings.market_sync_interval_seconds * 2, 60),
    )
    return RuntimeComponents(
        settings=settings,
        readiness=readiness,
        strategy=strategy,
        logging_runtime=logging_runtime,
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
        market_discovery_scan=market_discovery_scan,
        strategy_service=strategy_service,
        trading_service=trading_service,
        strategy_worker=strategy_worker,
        reconcile_service=reconcile_service,
        reconcile_worker=reconcile_worker,
        scheduler=scheduler,
        supervisor=supervisor,
        metrics=metrics,
        trading_thread_pool=trading_thread_pool,
        maintenance_thread_pool=maintenance_thread_pool,
        maintenance_process_pool=maintenance_process_pool,
    )


async def create_runtime(settings: Settings | None = None) -> RuntimeComponents:
    runtime = build_runtime(settings)
    try:
        await bootstrap_runtime(runtime)
    except Exception:
        with suppress(Exception):
            await shutdown_runtime(runtime)
        raise
    return runtime


async def bootstrap_runtime(runtime: RuntimeComponents) -> RuntimeComponents:
    runtime.supervisor.set_phase(RuntimePhase.CONFIG_LOADING, reason="loading_settings")
    _register_runtime_workers(runtime)
    _seed_default_metrics(runtime)
    _sync_runtime_metrics(runtime)

    db_ready = await _check_database_connection(runtime.db_session_factory)
    runtime.supervisor.mark_db_ready(db_ready, reason="database_unavailable" if not db_ready else "")
    runtime.supervisor.mark_trading_client_ready(
        runtime.trading_client is not None and runtime.readiness.ready_to_trade,
        reason="trading_client_unavailable",
    )

    runtime.supervisor.set_phase(RuntimePhase.INFRA_READY, reason="infra_initialized")
    runtime.supervisor.set_phase(RuntimePhase.RECOVERING_SNAPSHOT, reason="loading_reference_state")
    loaded_reference = await _load_reference_state(runtime)

    reconcile_summary: dict[str, Any]
    runtime.supervisor.set_phase(RuntimePhase.RECONCILING, reason="startup_reconcile")
    try:
        result = await _run_reconcile_once(runtime, source="startup")
        reconcile_summary = {
            "trace_id": result.trace_id,
            "markets": len(result.plan.market_plans),
            "diff_count": result.plan.diff_count,
            "applied_actions": len(result.applied_actions),
            "failed_actions": len(result.failed_actions),
        }
    except Exception as exc:  # pragma: no cover - startup may fail on live dependencies
        reconcile_summary = {"error": str(exc)}
        runtime.supervisor.mark_degraded(f"startup_reconcile_failed:{exc}")
        logger.warning(
            "startup reconcile failed; runtime remains degraded",
            extra={"reason": str(exc)},
        )

    _start_background_tasks(runtime)
    _register_scheduler_jobs(runtime)
    runtime.scheduler.start_all()
    runtime.supervisor.set_phase(RuntimePhase.WORKERS_STARTED, reason="background_workers_started")
    _sync_runtime_metrics(runtime)
    snapshot = await runtime.supervisor.refresh()
    runtime.metrics.set_trading_gate(
        snapshot.automatic_trading_enabled,
        reason=snapshot.status_reason,
        source="supervisor",
    )
    runtime.bootstrap_summary.update(
        {
            "loaded_reference": loaded_reference,
            "startup_reconcile": reconcile_summary,
        }
    )
    if not snapshot.readiness or not snapshot.readiness.ready:
        logger.warning(
            "runtime bootstrapped in safe mode; automatic trading remains disabled",
            extra={"readiness": None if snapshot.readiness is None else snapshot.readiness.as_dict()},
        )
    return runtime


async def shutdown_runtime(runtime: RuntimeComponents) -> None:
    runtime.supervisor.set_phase(RuntimePhase.STOPPING, reason="shutdown_requested")
    runtime.metrics.set_trading_gate(False, reason="shutdown", source="runtime")
    await runtime.scheduler.shutdown()

    runtime.persistence_worker.stop()
    tasks = list(runtime.background_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    runtime.background_tasks.clear()

    with suppress(Exception):
        await runtime.order_executor.aclose()
    for client in (runtime.gamma_client, runtime.clob_client, runtime.data_client):
        with suppress(Exception):
            await client.aclose()
    bind = getattr(runtime.db_session_factory, "kw", {}).get("bind")
    if bind is not None:
        with suppress(Exception):
            await bind.dispose()
    runtime.trading_thread_pool.shutdown(wait=False, cancel_futures=True)
    runtime.maintenance_thread_pool.shutdown(wait=False, cancel_futures=True)
    runtime.maintenance_process_pool.shutdown(wait=False, cancel_futures=True)
    runtime.logging_runtime.shutdown()
    runtime.supervisor.set_phase(RuntimePhase.STOPPED, reason="shutdown_complete")


async def run() -> RuntimeComponents:
    return await create_runtime()


def main() -> None:
    asyncio.run(run())


def _register_runtime_workers(runtime: RuntimeComponents) -> None:
    runtime.supervisor.register_worker("admin_api", priority="P3", state=WorkerLifecycleState.RUNNING)
    runtime.supervisor.register_worker("market_discovery", priority="P2")
    runtime.supervisor.register_worker("market_ws", priority="P0", state=WorkerLifecycleState.PAUSED)
    runtime.supervisor.register_worker("user_ws", priority="P0", state=WorkerLifecycleState.PAUSED)
    runtime.supervisor.register_worker("strategy", priority="P0")
    runtime.supervisor.register_worker("reconcile", priority="P2")
    runtime.supervisor.register_worker("persistence", priority="P3")


def _seed_default_metrics(runtime: RuntimeComponents) -> None:
    for gauge_name in (
        "entry_signal_to_submit_ms",
        "trading_lock_wait_ms",
        "executor_queue_wait_ms",
        "ws_event_lag_ms",
    ):
        runtime.metrics.set_gauge(gauge_name, 0.0)
    runtime.metrics.set_trading_gate(False, reason="bootstrap", source="runtime")


async def _check_database_connection(
    session_factory: async_sessionmaker[AsyncSession],
) -> bool:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - depends on external db
        logger.warning("database readiness check failed", extra={"reason": str(exc)})
        return False


def _restore_account_reference_state(runtime: RuntimeComponents, *, balance_usdc, allowance_usdc) -> None:
    runtime.account_state_store.update_balances(
        balance_usdc=balance_usdc,
        allowance_usdc=allowance_usdc,
    )


async def _load_reference_state(runtime: RuntimeComponents) -> dict[str, int]:
    loaded = {"markets": 0, "positions": 0, "open_orders": 0, "fills": 0, "account_snapshots": 0}
    try:
        async with runtime.db_session_factory() as session:
            account_snapshot = await AccountSnapshotRepository(session).get_current_snapshot()
            markets = await MarketRepository(session).list_markets_snapshot(limit=500, offset=0)
            positions = await PositionRepository(session).list_positions_snapshot(limit=500, offset=0)
            open_orders = await OrderRepository(session).list_open_orders_snapshot(limit=500, offset=0)
            fills = await FillRepository(session).list_fills_snapshot(limit=500, offset=0)
        if account_snapshot is not None:
            _restore_account_reference_state(
                runtime,
                balance_usdc=account_snapshot.balance_usdc,
                allowance_usdc=account_snapshot.allowance_usdc,
            )
        for market in markets.items:
            runtime.market_ws_worker.track_market(market)
        runtime.account_state_store.replace_positions(positions.items)
        runtime.account_state_store.replace_open_orders(open_orders.items)
        runtime.account_state_store.replace_fills(fills.items)
        loaded = {
            "account_snapshots": 0 if account_snapshot is None else 1,
            "markets": len(markets.items),
            "positions": len(positions.items),
            "open_orders": len(open_orders.items),
            "fills": len(fills.items),
        }
    except Exception as exc:  # pragma: no cover - depends on external db
        logger.warning("failed to load reference state from database", extra={"reason": str(exc)})
    return loaded


def _market_ws_subscription_token_ids(runtime: RuntimeComponents) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                token_id
                for market in runtime.registry.snapshot().markets
                for token_id in (market.no_token_id, market.yes_token_id)
                if token_id
            }
        )
    )


def _user_ws_subscription_condition_ids(runtime: RuntimeComponents) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                market.condition_id
                for market in runtime.registry.snapshot().markets
                if market.condition_id
            }
        )
    )


def _user_ws_auth_payload(runtime: RuntimeComponents) -> dict[str, str] | None:
    if runtime.trading_client is None:
        return None
    credentials = runtime.trading_client.get_api_credentials()
    return {
        "apiKey": credentials.api_key,
        "secret": credentials.api_secret,
        "passphrase": credentials.api_passphrase,
    }


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task


def _drain_queue(queue: asyncio.Queue[Mapping[str, Any]]) -> None:
    while not queue.empty():
        with suppress(asyncio.QueueEmpty):
            queue.get_nowait()


async def _stream_market_ws_messages(
    runtime: RuntimeComponents,
    token_ids: tuple[str, ...],
    queue: asyncio.Queue[Mapping[str, Any]],
) -> None:
    async def on_connect(attempt: int) -> None:
        runtime.supervisor.heartbeat_worker(
            "market_ws",
            state=WorkerLifecycleState.RUNNING,
            healthy=True,
            detail=f"connected subscribed={len(token_ids)} attempt={attempt}",
        )
        _sync_runtime_metrics(runtime)

    async def on_disconnect(attempt: int) -> None:
        runtime.supervisor.heartbeat_worker(
            "market_ws",
            state=WorkerLifecycleState.PAUSED,
            healthy=True,
            detail=f"disconnected attempt={attempt}",
        )
        _sync_runtime_metrics(runtime)

    async def on_reconnect(attempt: int, exc: Exception) -> None:
        runtime.market_ws_worker.record_error(str(exc))
        runtime.supervisor.heartbeat_worker(
            "market_ws",
            state=WorkerLifecycleState.DEGRADED,
            healthy=False,
            detail=f"reconnecting attempt={attempt}",
            last_error=str(exc),
        )
        _sync_runtime_metrics(runtime)

    async for message in runtime.polymarket_ws_client.stream_market_messages(
        token_ids,
        reconnect=True,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_reconnect=on_reconnect,
    ):
        payload = message.payload if isinstance(message.payload, Mapping) else message.raw
        await queue.put(dict(payload))


def _market_ws_message_type(message: Mapping[str, Any]) -> str:
    value = (
        message.get("event_type")
        or message.get("message_type")
        or message.get("channel_event")
        or message.get("event")
        or message.get("type")
        or message.get("action")
    )
    return "" if value is None else str(value).strip().lower()


async def _handle_market_ws_message(
    runtime: RuntimeComponents,
    message: Mapping[str, Any],
) -> None:
    if _market_ws_message_type(message) == "new_market":
        await runtime.market_discovery_worker.ingest_ws_new_market(
            message,
            trace_id=f"market-ws-discovery-{uuid4().hex}",
        )
    await runtime.market_ws_worker.handle_message(message, source="market_ws")


async def _stream_user_ws_messages(
    runtime: RuntimeComponents,
    condition_ids: tuple[str, ...],
    auth: Mapping[str, str],
    queue: asyncio.Queue[Mapping[str, Any]],
) -> None:
    async def on_connect(attempt: int) -> None:
        await runtime.user_ws_worker.set_connection_state(
            True,
            trace_id=f"user-ws-connected-{uuid4().hex}",
            reason="user_ws_connected",
        )
        runtime.supervisor.heartbeat_worker(
            "user_ws",
            state=WorkerLifecycleState.RUNNING,
            healthy=True,
            detail=f"connected subscribed={len(condition_ids)} attempt={attempt}",
        )
        _sync_runtime_metrics(runtime)

    async def on_disconnect(attempt: int) -> None:
        await runtime.user_ws_worker.set_connection_state(
            False,
            trace_id=f"user-ws-disconnected-{uuid4().hex}",
            reason="user_ws_disconnected",
        )
        runtime.supervisor.heartbeat_worker(
            "user_ws",
            state=WorkerLifecycleState.PAUSED,
            healthy=True,
            detail=f"disconnected attempt={attempt}",
        )
        _sync_runtime_metrics(runtime)

    async def on_reconnect(attempt: int, exc: Exception) -> None:
        runtime.user_ws_worker.record_error(str(exc))
        await runtime.user_ws_worker.set_connection_state(
            False,
            trace_id=f"user-ws-reconnecting-{uuid4().hex}",
            reason="user_ws_reconnecting",
        )
        runtime.supervisor.heartbeat_worker(
            "user_ws",
            state=WorkerLifecycleState.DEGRADED,
            healthy=False,
            detail=f"reconnecting attempt={attempt}",
            last_error=str(exc),
        )
        _sync_runtime_metrics(runtime)

    async for message in runtime.polymarket_ws_client.stream_user_messages(
        condition_ids,
        auth=auth,
        reconnect=True,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_reconnect=on_reconnect,
    ):
        payload = message.payload if isinstance(message.payload, Mapping) else message.raw
        await queue.put(dict(payload))


async def _run_market_ws(runtime: RuntimeComponents) -> None:
    queue: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue(maxsize=512)
    stream_task: asyncio.Task[None] | None = None
    subscribed_token_ids: tuple[str, ...] = ()
    try:
        while True:
            if stream_task is not None and stream_task.done():
                exc = None if stream_task.cancelled() else stream_task.exception()
                if exc is not None:
                    runtime.market_ws_worker.record_error(str(exc))
                    runtime.supervisor.mark_worker_error(
                        "market_ws",
                        detail="stream_failed",
                        last_error=str(exc),
                    )
                stream_task = None
                subscribed_token_ids = ()

            desired_token_ids = _market_ws_subscription_token_ids(runtime)
            if desired_token_ids != subscribed_token_ids:
                await _cancel_task(stream_task)
                stream_task = None
                subscribed_token_ids = ()
                _drain_queue(queue)
                if desired_token_ids:
                    runtime.market_ws_worker.build_subscription_request(desired_token_ids)
                    stream_task = asyncio.create_task(
                        _stream_market_ws_messages(runtime, desired_token_ids, queue),
                        name="trader:market-ws-stream",
                    )
                    subscribed_token_ids = desired_token_ids
                    runtime.supervisor.heartbeat_worker(
                        "market_ws",
                        state=WorkerLifecycleState.RUNNING,
                        healthy=True,
                        detail=f"subscribing count={len(subscribed_token_ids)}",
                    )
                else:
                    runtime.supervisor.heartbeat_worker(
                        "market_ws",
                        state=WorkerLifecycleState.PAUSED,
                        healthy=True,
                        detail="no_markets",
                    )
                    _sync_runtime_metrics(runtime)

            try:
                message = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            await _handle_market_ws_message(runtime, message)
            runtime.supervisor.heartbeat_worker(
                "market_ws",
                state=WorkerLifecycleState.RUNNING,
                healthy=True,
                detail=f"subscribed={len(subscribed_token_ids)}",
            )
            _sync_runtime_metrics(runtime)
    except asyncio.CancelledError:
        await _cancel_task(stream_task)
        runtime.supervisor.heartbeat_worker(
            "market_ws",
            state=WorkerLifecycleState.STOPPED,
            healthy=True,
            detail="cancelled",
        )
        raise


async def _run_user_ws(runtime: RuntimeComponents) -> None:
    queue: asyncio.Queue[Mapping[str, Any]] = asyncio.Queue(maxsize=512)
    stream_task: asyncio.Task[None] | None = None
    subscribed_condition_ids: tuple[str, ...] = ()
    subscribed_auth: dict[str, str] | None = None
    try:
        while True:
            if stream_task is not None and stream_task.done():
                exc = None if stream_task.cancelled() else stream_task.exception()
                if exc is not None:
                    runtime.user_ws_worker.record_error(str(exc))
                    runtime.supervisor.mark_worker_error(
                        "user_ws",
                        detail="stream_failed",
                        last_error=str(exc),
                    )
                stream_task = None
                subscribed_condition_ids = ()
                subscribed_auth = None

            desired_condition_ids = _user_ws_subscription_condition_ids(runtime)
            try:
                desired_auth = _user_ws_auth_payload(runtime) if desired_condition_ids else None
            except Exception as exc:
                runtime.user_ws_worker.record_error(str(exc))
                await runtime.user_ws_worker.set_connection_state(
                    False,
                    trace_id=f"user-ws-auth-failed-{uuid4().hex}",
                    reason="user_ws_auth_failed",
                )
                runtime.supervisor.mark_worker_error(
                    "user_ws",
                    detail="auth_failed",
                    last_error=str(exc),
                )
                _sync_runtime_metrics(runtime)
                await asyncio.sleep(5.0)
                continue

            if desired_condition_ids != subscribed_condition_ids or desired_auth != subscribed_auth:
                await _cancel_task(stream_task)
                stream_task = None
                subscribed_condition_ids = ()
                subscribed_auth = None
                _drain_queue(queue)
                if desired_condition_ids and desired_auth is not None:
                    runtime.user_ws_worker.build_subscription_request(
                        desired_condition_ids,
                        auth=desired_auth,
                    )
                    stream_task = asyncio.create_task(
                        _stream_user_ws_messages(runtime, desired_condition_ids, desired_auth, queue),
                        name="trader:user-ws-stream",
                    )
                    subscribed_condition_ids = desired_condition_ids
                    subscribed_auth = dict(desired_auth)
                    runtime.supervisor.heartbeat_worker(
                        "user_ws",
                        state=WorkerLifecycleState.RUNNING,
                        healthy=True,
                        detail=f"subscribing count={len(subscribed_condition_ids)}",
                    )
                else:
                    await runtime.user_ws_worker.set_connection_state(
                        False,
                        trace_id=f"user-ws-paused-{uuid4().hex}",
                        reason="user_ws_not_started",
                    )
                    runtime.supervisor.heartbeat_worker(
                        "user_ws",
                        state=WorkerLifecycleState.PAUSED,
                        healthy=True,
                        detail="no_markets_or_auth",
                    )
                    _sync_runtime_metrics(runtime)

            try:
                message = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            await runtime.user_ws_worker.process_message(message)
            runtime.supervisor.heartbeat_worker(
                "user_ws",
                state=WorkerLifecycleState.RUNNING,
                healthy=True,
                detail=f"subscribed={len(subscribed_condition_ids)}",
            )
            _sync_runtime_metrics(runtime)
    except asyncio.CancelledError:
        await _cancel_task(stream_task)
        await runtime.user_ws_worker.set_connection_state(
            False,
            trace_id=f"user-ws-stopped-{uuid4().hex}",
            reason="user_ws_stopped",
        )
        runtime.supervisor.heartbeat_worker(
            "user_ws",
            state=WorkerLifecycleState.STOPPED,
            healthy=True,
            detail="cancelled",
        )
        raise


def _start_background_tasks(runtime: RuntimeComponents) -> None:
    runtime.background_tasks["market_ws"] = asyncio.create_task(
        _run_supervised_loop(
            runtime,
            name="market_ws",
            runner=lambda: _run_market_ws(runtime),
        ),
        name="trader:market-ws",
    )
    runtime.background_tasks["user_ws"] = asyncio.create_task(
        _run_supervised_loop(
            runtime,
            name="user_ws",
            runner=lambda: _run_user_ws(runtime),
        ),
        name="trader:user-ws",
    )
    runtime.background_tasks["strategy"] = asyncio.create_task(
        _run_supervised_loop(
            runtime,
            name="strategy",
            runner=runtime.strategy_worker.run,
        ),
        name="trader:strategy",
    )
    runtime.background_tasks["reconcile"] = asyncio.create_task(
        _run_supervised_loop(
            runtime,
            name="reconcile",
            runner=lambda: _run_reconcile(runtime),
        ),
        name="trader:reconcile",
    )
    runtime.background_tasks["persistence"] = asyncio.create_task(
        _run_supervised_loop(
            runtime,
            name="persistence",
            runner=runtime.persistence_worker.run,
        ),
        name="trader:persistence",
    )


def _register_scheduler_jobs(runtime: RuntimeComponents) -> None:
    runtime.scheduler.register_job(
        "market_discovery_scan",
        lambda: _run_market_discovery_scan(runtime),
        priority="P2",
        interval_seconds=_MARKET_DISCOVERY_TICK_SECONDS,
        tags=("market_discovery",),
        start=True,
        run_immediately=True,
    )
    runtime.scheduler.register_job(
        "periodic_reconcile",
        lambda: _publish_reconcile_trigger(runtime, source="scheduled"),
        priority="P2",
        interval_seconds=float(runtime.settings.market_sync_interval_seconds),
        tags=("reconcile",),
        start=True,
        run_immediately=False,
    )
    runtime.scheduler.register_job(
        "supervisor_refresh",
        lambda: _run_supervisor_refresh(runtime),
        priority="P2",
        interval_seconds=5.0,
        tags=("supervisor", "metrics"),
        start=True,
        run_immediately=True,
    )


async def _run_supervised_loop(
    runtime: RuntimeComponents,
    *,
    name: str,
    runner: Any,
) -> None:
    runtime.supervisor.heartbeat_worker(name, detail="starting")
    try:
        await runner()
    except asyncio.CancelledError:
        runtime.supervisor.heartbeat_worker(
            name,
            state=WorkerLifecycleState.STOPPED,
            healthy=True,
            detail="cancelled",
        )
        raise
    except Exception as exc:
        runtime.supervisor.mark_worker_error(name, detail="loop_failed", last_error=str(exc))
        raise


async def _run_market_discovery_scan(runtime: RuntimeComponents) -> None:
    state = runtime.market_discovery_scan
    if (
        runtime.market_discovery_worker.last_failure is not None
        and not runtime.market_discovery_worker.should_retry()
    ):
        retry_at = runtime.market_discovery_worker.last_failure.retry_at.isoformat()
        runtime.supervisor.heartbeat_worker(
            "market_discovery",
            detail=f"retry_backoff until={retry_at}",
        )
        _sync_runtime_metrics(runtime)
        return

    state.start_tick()
    runtime.supervisor.heartbeat_worker(
        "market_discovery",
        detail=(
            f"round={state.round_id} cursor={'set' if state.after_cursor else 'start'} "
            f"budget={_MARKET_DISCOVERY_REQUEST_BUDGET_PER_TICK}"
        ),
    )
    started_at = asyncio.get_running_loop().time()
    try:
        round_completed = False
        completed_round_id: int | None = None
        completed_round_pages = 0
        completed_round_markets = 0
        while (
            state.last_tick_requests < _MARKET_DISCOVERY_REQUEST_BUDGET_PER_TICK
            and state.last_tick_markets < _MARKET_DISCOVERY_MARKET_BUDGET_PER_TICK
        ):
            elapsed_ms = (asyncio.get_running_loop().time() - started_at) * 1000.0
            if elapsed_ms >= _MARKET_DISCOVERY_MAX_RUNTIME_MS:
                break
            page_markets, next_cursor = await _fetch_full_market_discovery_page(runtime)
            runtime.market_discovery_worker.mark_scan_success()
            market_payloads = tuple(raw_event.payload for raw_event in page_markets)
            state.record_page(page_size=len(market_payloads), next_cursor=next_cursor)
            if market_payloads:
                runtime.metrics.inc_counter(
                    "market_discovery_markets_scanned_total",
                    float(len(market_payloads)),
                )
                runtime.metrics.inc_counter("market_discovery_requests_total", 1.0)
                runtime.metrics.inc_counter("market_discovery_pages_scanned_total", 1.0)
            else:
                runtime.metrics.inc_counter("market_discovery_requests_total", 1.0)
                runtime.metrics.inc_counter("market_discovery_pages_scanned_total", 1.0)

            await runtime.market_discovery_worker.ingest_source_page(
                {"markets": list(market_payloads)},
                source="gamma.events_keyset",
                trace_id=f"market-discovery-round-{state.round_id}-{uuid4().hex}",
            )
            if next_cursor is None:
                round_completed = True
                completed_round_id = state.round_id
                completed_round_pages = state.pages_scanned_in_round
                completed_round_markets = state.markets_seen_in_round
                state.finish_round()
                runtime.metrics.inc_counter("market_discovery_rounds_completed_total", 1.0)
                break
            if state.last_tick_markets >= _MARKET_DISCOVERY_MARKET_BUDGET_PER_TICK:
                break
    except Exception as exc:  # pragma: no cover - depends on external gamma
        state.record_failure(str(exc))
        runtime.market_discovery_worker.record_failure(
            source="gamma.events_keyset",
            reason=str(exc),
            retry_after_seconds=_MARKET_DISCOVERY_RETRY_BACKOFF_SECONDS,
        )
        runtime.supervisor.mark_worker_error(
            "market_discovery",
            detail="discover_failed",
            last_error=str(exc),
        )
        logger.warning("market discovery scan failed", extra={"reason": str(exc)})
    else:
        state.finish_tick()
        if round_completed and completed_round_id is not None:
            runtime.supervisor.heartbeat_worker(
                "market_discovery",
                detail=(
                    f"round_completed={completed_round_id} "
                    f"pages={completed_round_pages} markets={completed_round_markets}"
                ),
            )
        else:
            runtime.supervisor.heartbeat_worker(
                "market_discovery",
                detail=(
                    f"round={state.round_id} reqs={state.last_tick_requests} "
                    f"markets={state.last_tick_markets} cursor={'set' if state.after_cursor else 'start'}"
                ),
            )
    finally:
        _sync_runtime_metrics(runtime)


async def _fetch_full_market_discovery_page(
    runtime: RuntimeComponents,
) -> tuple[tuple[Any, ...], str | None]:
    params: dict[str, Any] = {
        "active": True,
        "closed": False,
        "limit": _MARKET_DISCOVERY_EVENT_PAGE_LIMIT,
    }
    if runtime.market_discovery_scan.after_cursor is not None:
        params["after_cursor"] = runtime.market_discovery_scan.after_cursor
    events, next_cursor = await runtime.gamma_client.list_events_keyset_by_params(params)
    raw_events: list[Any] = []
    for event in events:
        raw_events.extend(event.to_raw_market_events(source="gamma.events_keyset"))
    return tuple(raw_events), next_cursor


async def _publish_reconcile_trigger(
    runtime: RuntimeComponents,
    *,
    source: str,
) -> None:
    await runtime.event_bus.publish(
        OutboxPriority.P2,
        DomainEvent(
            trace_id=f"reconcile-trigger-{source}-{uuid4().hex}",
            event_type=f"reconcile_{source}",
            event_id=uuid4().hex,
            reason=source,
            payload={"source": source},
        ),
    )
    _sync_runtime_metrics(runtime)


def _is_reconcile_trigger(event: DomainEvent) -> bool:
    event_type = str(event.event_type)
    if event_type.startswith("reconcile_"):
        return True
    return event_type in {
        "market_discovered",
        "market_updated",
        "market_filtered_in",
        "market_filtered_out",
        "market_resolved_or_disabled",
    }


def _coalesce_reconcile_scope(
    events: tuple[DomainEvent, ...],
) -> tuple[str, DomainEvent, tuple[str, ...] | None]:
    trigger = events[-1]
    source_event_types = {str(event.event_type) for event in events}
    if len(source_event_types) == 1:
        source = f"event:{next(iter(source_event_types))}"
    else:
        source = f"event-batch:{len(events)}"

    condition_ids: list[str] = []
    seen_condition_ids: set[str] = set()
    for event in events:
        condition_id = getattr(event, "condition_id", None)
        if not condition_id:
            return source, trigger, None
        if condition_id in seen_condition_ids:
            continue
        seen_condition_ids.add(condition_id)
        condition_ids.append(condition_id)
    return source, trigger, tuple(condition_ids)


async def _run_reconcile(runtime: RuntimeComponents) -> None:
    max_batch_size = max(1, min(runtime.settings.maintenance_event_queue_max_size, 256))
    while True:
        first_trigger = await runtime.event_bus.next_maintenance_event()
        pending_events: list[DomainEvent] = [first_trigger]
        while (
            runtime.event_bus.maintenance_queue_depth() > 0
            and len(pending_events) < max_batch_size
        ):
            pending_events.append(await runtime.event_bus.next_maintenance_event())

        actionable_events = tuple(event for event in pending_events if _is_reconcile_trigger(event))
        if not actionable_events:
            _sync_runtime_metrics(runtime)
            continue

        source, trigger, condition_ids = _coalesce_reconcile_scope(actionable_events)
        await _run_reconcile_once(
            runtime,
            source=source,
            trigger_event=trigger,
            condition_ids=condition_ids,
        )


def _discovery_source(query: DiscoveryQuery) -> str:
    return f"gamma.{query.endpoint.value}"


def _normalize_page_limit(query: DiscoveryQuery) -> int:
    raw_limit = query.params.get("limit", 100)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return 100
    return max(1, min(limit, 500))


def _normalize_offset(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _normalize_discovery_params(params: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in params.items():
        if value is None:
            continue
        normalized[key] = value
    return normalized


async def _execute_discovery_query(
    gamma_client: GammaClient,
    query: DiscoveryQuery,
) -> tuple[Mapping[str, Any], ...]:
    if query.max_pages < 1:
        return ()
    if query.endpoint is DiscoveryEndpoint.EVENTS:
        return await _execute_events_query(gamma_client, query)
    if query.endpoint is DiscoveryEndpoint.EVENTS_KEYSET:
        return await _execute_events_keyset_query(gamma_client, query)
    if query.endpoint is DiscoveryEndpoint.MARKETS:
        return await _execute_markets_query(gamma_client, query)
    if query.endpoint is DiscoveryEndpoint.MARKETS_KEYSET:
        return await _execute_markets_keyset_query(gamma_client, query)
    raise ValueError(f"unsupported discovery endpoint: {query.endpoint!r}")


async def _execute_events_query(
    gamma_client: GammaClient,
    query: DiscoveryQuery,
) -> tuple[Mapping[str, Any], ...]:
    params = _normalize_discovery_params(query.params)
    limit = _normalize_page_limit(query)
    base_offset = _normalize_offset(params.get("offset", 0))
    payloads: list[Mapping[str, Any]] = []
    for page_index in range(query.max_pages):
        page_params = dict(params)
        page_params["limit"] = limit
        page_params["offset"] = base_offset + page_index * limit
        events = await gamma_client.list_events_by_params(page_params, timeout_s=query.timeout_s)
        for event in events:
            payloads.extend(raw.payload for raw in event.to_raw_market_events(source=_discovery_source(query)))
        if len(events) < limit:
            break
    return tuple(payloads)


async def _execute_events_keyset_query(
    gamma_client: GammaClient,
    query: DiscoveryQuery,
) -> tuple[Mapping[str, Any], ...]:
    params = _normalize_discovery_params(query.params)
    if "offset" in params:
        raise ValueError("events_keyset discovery queries must not include offset")
    limit = _normalize_page_limit(query)
    after_cursor = params.get("after_cursor")
    payloads: list[Mapping[str, Any]] = []
    for _ in range(query.max_pages):
        page_params = dict(params)
        page_params["limit"] = limit
        if after_cursor is not None:
            page_params["after_cursor"] = after_cursor
        events, next_cursor = await gamma_client.list_events_keyset_by_params(
            page_params,
            timeout_s=query.timeout_s,
        )
        for event in events:
            payloads.extend(raw.payload for raw in event.to_raw_market_events(source=_discovery_source(query)))
        if not events or not next_cursor:
            break
        after_cursor = next_cursor
    return tuple(payloads)


async def _execute_markets_query(
    gamma_client: GammaClient,
    query: DiscoveryQuery,
) -> tuple[Mapping[str, Any], ...]:
    params = _normalize_discovery_params(query.params)
    limit = _normalize_page_limit(query)
    base_offset = _normalize_offset(params.get("offset", 0))
    payloads: list[Mapping[str, Any]] = []
    for page_index in range(query.max_pages):
        page_params = dict(params)
        page_params["limit"] = limit
        page_params["offset"] = base_offset + page_index * limit
        markets = await gamma_client.list_markets_by_params(page_params, timeout_s=query.timeout_s)
        payloads.extend(market.raw for market in markets)
        if len(markets) < limit:
            break
    return tuple(payloads)


async def _execute_markets_keyset_query(
    gamma_client: GammaClient,
    query: DiscoveryQuery,
) -> tuple[Mapping[str, Any], ...]:
    params = _normalize_discovery_params(query.params)
    if "offset" in params:
        raise ValueError("markets_keyset discovery queries must not include offset")
    limit = _normalize_page_limit(query)
    after_cursor = params.get("after_cursor")
    payloads: list[Mapping[str, Any]] = []
    for _ in range(query.max_pages):
        page_params = dict(params)
        page_params["limit"] = limit
        if after_cursor is not None:
            page_params["after_cursor"] = after_cursor
        markets, next_cursor = await gamma_client.list_markets_keyset_by_params(
            page_params,
            timeout_s=query.timeout_s,
        )
        payloads.extend(market.raw for market in markets)
        if not markets or not next_cursor:
            break
        after_cursor = next_cursor
    return tuple(payloads)


async def _run_reconcile_once(
    runtime: RuntimeComponents,
    *,
    source: str,
    trigger_event: DomainEvent | None = None,
    condition_ids: tuple[str, ...] | None = None,
) -> Any:
    runtime.supervisor.heartbeat_worker("reconcile", detail=source)
    started_at = asyncio.get_running_loop().time()
    try:
        result = await runtime.reconcile_worker.reconcile_once(
            trace_id=f"reconcile-{source}-{uuid4().hex}",
            trigger_event=trigger_event,
            condition_ids=condition_ids,
        )
    except Exception as exc:
        duration_ms = (asyncio.get_running_loop().time() - started_at) * 1000.0
        runtime.metrics.record_reconcile(
            duration_ms,
            started_at=runtime.reconcile_worker.status_snapshot().last_started_at,
            completed_at=None,
            status="failed",
            error=str(exc),
            trace_id=runtime.reconcile_worker.status_snapshot().last_trace_id,
            actions=0,
        )
        runtime.supervisor.mark_worker_error("reconcile", detail="reconcile_failed", last_error=str(exc))
        _sync_runtime_metrics(runtime)
        raise
    duration_ms = (asyncio.get_running_loop().time() - started_at) * 1000.0
    status = runtime.reconcile_worker.status_snapshot()
    runtime.metrics.record_reconcile(
        duration_ms,
        started_at=status.last_started_at,
        completed_at=status.last_completed_at,
        status="ok",
        error=None,
        trace_id=status.last_trace_id,
        actions=len(result.applied_actions),
    )
    runtime.supervisor.heartbeat_worker(
        "reconcile",
        detail=f"applied={len(result.applied_actions)} failed={len(result.failed_actions)}",
    )
    _sync_runtime_metrics(runtime)
    return result


async def _run_supervisor_refresh(runtime: RuntimeComponents) -> None:
    _sync_runtime_metrics(runtime)
    snapshot = await runtime.supervisor.refresh()
    runtime.metrics.set_trading_gate(
        snapshot.automatic_trading_enabled,
        reason=snapshot.status_reason,
        source="supervisor",
    )


def _sync_runtime_metrics(runtime: RuntimeComponents) -> None:
    queue_snapshot = runtime.event_bus.snapshot()
    runtime.metrics.set_queue_depth(
        "trading_queue_depth",
        queue_snapshot.trading_queue_depth,
        capacity=queue_snapshot.trading_queue_capacity,
        retained_depth=queue_snapshot.trading_retained_depth,
        paused=False,
    )
    runtime.metrics.set_queue_depth(
        "maintenance_queue_depth",
        queue_snapshot.maintenance_queue_depth,
        capacity=queue_snapshot.maintenance_queue_capacity,
        retained_depth=queue_snapshot.maintenance_retained_depth,
        paused=queue_snapshot.low_priority_paused,
    )
    runtime.metrics.set_queue_depth(
        "persistence_queue_depth",
        queue_snapshot.persistence_queue_depth,
        capacity=queue_snapshot.persistence_queue_capacity,
        retained_depth=queue_snapshot.persistence_retained_depth,
        paused=queue_snapshot.low_priority_paused,
    )
    market_ws = runtime.market_ws_worker.status_snapshot()
    market_last_event = None
    if market_ws.last_result is not None and market_ws.last_result.event_types:
        market_last_event = market_ws.last_result.event_types[-1]
    runtime.metrics.set_ws_state(
        "market_ws",
        connected=market_ws.last_error is None,
        subscribed_count=market_ws.subscription_count,
        last_message_at=market_ws.last_message_at,
        last_event_type=market_last_event,
        last_error=market_ws.last_error,
    )
    user_ws = runtime.user_ws_worker.status_snapshot()
    runtime.metrics.set_ws_state(
        "user_ws",
        connected=user_ws.connected,
        subscribed_count=user_ws.subscription_count,
        last_message_at=user_ws.last_message_at,
        last_event_type=None if user_ws.last_result is None else user_ws.last_result.message_type,
        last_error=user_ws.last_error,
        reconnect_attempts=0,
    )
    reconcile = runtime.reconcile_worker.status_snapshot()
    if reconcile.last_completed_at is not None:
        runtime.metrics.mark_timestamp("last_reconcile_at", at=reconcile.last_completed_at)
    discovery = runtime.market_discovery_scan
    runtime.metrics.set_gauge("market_discovery_round_id", float(discovery.round_id))
    runtime.metrics.set_gauge(
        "market_discovery_pages_scanned_in_round",
        float(discovery.pages_scanned_in_round),
    )
    runtime.metrics.set_gauge(
        "market_discovery_markets_seen_in_round",
        float(discovery.markets_seen_in_round),
    )
    runtime.metrics.set_gauge(
        "market_discovery_last_page_size",
        float(discovery.last_page_size),
    )
    runtime.metrics.set_gauge(
        "market_discovery_after_cursor_present",
        1.0 if discovery.after_cursor is not None else 0.0,
    )
    runtime.metrics.set_gauge(
        "market_discovery_last_tick_requests",
        float(discovery.last_tick_requests),
    )
    runtime.metrics.set_gauge(
        "market_discovery_last_tick_markets",
        float(discovery.last_tick_markets),
    )
    runtime.metrics.set_gauge(
        "market_discovery_consecutive_failures",
        float(discovery.consecutive_failures),
    )
    if discovery.last_round_completed_at is not None:
        runtime.metrics.mark_timestamp(
            "market_discovery_last_round_completed_at",
            at=discovery.last_round_completed_at,
        )
    persistence = runtime.persistence_worker.snapshot()
    runtime.metrics.set_gauge("outbox_depth", persistence.outbox_depth)
    runtime.metrics.set_gauge("outbox_retained_depth", persistence.outbox_retained_depth)
    runtime.metrics.set_gauge("outbox_dead_letter_depth", persistence.outbox_dead_letter_depth)
    runtime.metrics.set_gauge("persistence_retry_count", persistence.retried_events)


if __name__ == "__main__":
    main()
