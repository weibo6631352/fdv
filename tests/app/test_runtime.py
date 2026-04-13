from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

from polymarket_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from polymarket_trader.config import Settings
from polymarket_trader.main import _execute_discovery_query, _run_market_discovery_scan, build_runtime
from polymarket_trader.strategy_api.models import DiscoveryEndpoint, DiscoveryQuery


def test_build_runtime_wires_m2_components() -> None:
    runtime = build_runtime(
        Settings(
            portfolio_budget_usdc=Decimal("100"),
            max_order_usdc=Decimal("25"),
            max_market_usdc=Decimal("50"),
            max_total_usdc=Decimal("100"),
            min_liquidity_usdc=Decimal("5"),
            max_spread=Decimal("0.10"),
            max_open_orders=10,
        )
    )

    assert runtime.market_discovery_worker is not None
    assert runtime.strategy.spec.name == "current"
    assert runtime.market_service is not None
    assert runtime.market_ws_worker is not None
    assert runtime.user_ws_worker is not None
    assert runtime.strategy_service is not None
    assert runtime.trading_service is not None
    assert runtime.strategy_worker is not None
    assert runtime.account_state_store is not None
    assert runtime.account_state_store.snapshot().user_ws_connected is False
    assert runtime.account_state_store.snapshot().allow_new_buys is False
    assert runtime.account_state_store.snapshot().last_reconcile_at is None
    assert runtime.order_executor is not None
    assert runtime.reconcile_service is not None
    assert runtime.reconcile_worker is not None
    assert runtime.strategy_worker.priority == "P0"


def test_build_runtime_binds_market_event_outbox_sink() -> None:
    async def run() -> None:
        runtime = build_runtime(
            Settings(
                portfolio_budget_usdc=Decimal("100"),
                max_order_usdc=Decimal("25"),
                max_market_usdc=Decimal("50"),
                max_total_usdc=Decimal("100"),
                min_liquidity_usdc=Decimal("5"),
                max_spread=Decimal("0.10"),
                max_open_orders=10,
            )
        )

        event = DomainEvent(
            trace_id="trace-market",
            event_type=DomainEventType.MARKET_UPDATED,
            event_id="event-market",
            market_slug="sample-market-a",
            condition_id="condition-500m",
            token_id="no-token-500m",
            reason="market_snapshot",
            payload={"market": {"condition_id": "condition-500m"}},
        )
        await runtime.event_bus.publish(OutboxPriority.P2, event)

        queued = await asyncio.wait_for(runtime.outbox.get(), timeout=0.1)
        assert queued.event_id == event.event_id
        assert queued.event_type == DomainEventType.MARKET_UPDATED.value
        assert queued.payload["market"]["condition_id"] == "condition-500m"

    asyncio.run(run())


def test_build_runtime_binds_user_event_outbox_sink_with_trimmed_payload() -> None:
    async def run() -> None:
        runtime = build_runtime(
            Settings(
                portfolio_budget_usdc=Decimal("100"),
                max_order_usdc=Decimal("25"),
                max_market_usdc=Decimal("50"),
                max_total_usdc=Decimal("100"),
                min_liquidity_usdc=Decimal("5"),
                max_spread=Decimal("0.10"),
                max_open_orders=10,
            )
        )

        event = DomainEvent(
            trace_id="trace-order",
            event_type=DomainEventType.ORDER_STATE_UPDATED,
            event_id="event-order",
            market_slug="sample-market-a",
            condition_id="condition-500m",
            token_id="no-token-500m",
            reason="order_update",
            payload={
                "order": {
                    "condition_id": "condition-500m",
                    "token_id": "no-token-500m",
                    "side": "BUY",
                    "order_type": "FAK",
                    "price": "0.60",
                },
                "snapshot": {"positions": []},
            },
        )
        await runtime.event_bus.publish(OutboxPriority.P0, event)

        queued = await asyncio.wait_for(runtime.outbox.get(), timeout=0.1)
        assert queued.event_id == event.event_id
        assert queued.event_type == DomainEventType.ORDER_STATE_UPDATED.value
        assert "order" in queued.payload
        assert "snapshot" not in queued.payload

    asyncio.run(run())


def test_build_runtime_binds_balance_event_outbox_sink() -> None:
    async def run() -> None:
        runtime = build_runtime(
            Settings(
                portfolio_budget_usdc=Decimal("100"),
                max_order_usdc=Decimal("25"),
                max_market_usdc=Decimal("50"),
                max_total_usdc=Decimal("100"),
                min_liquidity_usdc=Decimal("5"),
                max_spread=Decimal("0.10"),
                max_open_orders=10,
            )
        )

        event = DomainEvent(
            trace_id="trace-balance",
            event_type=DomainEventType.BALANCE_UPDATED,
            event_id="event-balance",
            reason="balance_update",
            payload={
                "balance_usdc": "120",
                "allowance_usdc": "90",
                "user_ws_connected": True,
                "allow_new_buys": True,
            },
        )
        await runtime.event_bus.publish(OutboxPriority.P0, event)

        queued = await asyncio.wait_for(runtime.outbox.get(), timeout=0.1)
        assert queued.event_id == event.event_id
        assert queued.event_type == DomainEventType.BALANCE_UPDATED.value
        assert str(queued.payload["balance_usdc"]) == "120"
        assert str(queued.payload["allowance_usdc"]) == "90"

    asyncio.run(run())


def test_execute_discovery_query_uses_keyset_cursor_pagination() -> None:
    class _StubGammaClient:
        def __init__(self) -> None:
            self.calls = []

        async def list_events_keyset_by_params(self, params, *, timeout_s=None):
            self.calls.append((dict(params), timeout_s))
            if len(self.calls) == 1:
                return (
                    (
                        SimpleNamespace(
                            to_raw_market_events=lambda **kwargs: (
                                SimpleNamespace(payload={"condition_id": "condition-1", "market_slug": "sample-market-a"}),
                            )
                        ),
                    ),
                    "cursor-2",
                )
            return (
                (
                    SimpleNamespace(
                        to_raw_market_events=lambda **kwargs: (
                            SimpleNamespace(payload={"condition_id": "condition-2", "market_slug": "sample-market-b"}),
                        )
                    ),
                ),
                None,
            )

    async def run() -> None:
        gamma = _StubGammaClient()
        payloads = await _execute_discovery_query(
            gamma,
            DiscoveryQuery(
                endpoint=DiscoveryEndpoint.EVENTS_KEYSET,
                params={"active": True, "closed": False, "title_search": "fdv", "limit": 100},
                max_pages=2,
            ),
        )

        assert [payload["condition_id"] for payload in payloads] == ["condition-1", "condition-2"]
        assert gamma.calls[0][0]["title_search"] == "fdv"
        assert "after_cursor" not in gamma.calls[0][0]
        assert gamma.calls[1][0]["after_cursor"] == "cursor-2"

    asyncio.run(run())


def test_run_market_discovery_scan_uses_strategy_queries() -> None:
    class _StubStrategy:
        def build_discovery_queries(self):
            return (
                DiscoveryQuery(
                    endpoint=DiscoveryEndpoint.EVENTS,
                    params={"active": True, "closed": False, "title_search": "fdv", "limit": 50},
                    max_pages=1,
                ),
            )

    class _StubGammaClient:
        def __init__(self) -> None:
            self.calls = []

        async def list_events_by_params(self, params, *, timeout_s=None):
            self.calls.append(dict(params))
            return (
                SimpleNamespace(
                    to_raw_market_events=lambda **kwargs: (
                        SimpleNamespace(payload={"condition_id": "condition-1", "market_slug": "sample-market-a"}),
                    )
                ),
            )

    class _StubDiscoveryWorker:
        def __init__(self) -> None:
            self.calls = []

        async def ingest_source_page(self, payload, *, source, trace_id):
            self.calls.append((payload, source, trace_id))

        def record_failure(self, *, source, reason):
            self.calls.append(("failure", source, reason))

    class _StubSupervisor:
        def heartbeat_worker(self, *args, **kwargs):
            return None

        def mark_worker_error(self, *args, **kwargs):
            return None

    class _StubMetrics:
        def set_queue_depth(self, *args, **kwargs):
            return None

        def set_ws_state(self, *args, **kwargs):
            return None

        def set_gauge(self, *args, **kwargs):
            return None

    class _StubEventBus:
        def snapshot(self):
            return SimpleNamespace(
                trading_queue_depth=0,
                trading_queue_capacity=1,
                trading_retained_depth=0,
                maintenance_queue_depth=0,
                maintenance_queue_capacity=1,
                maintenance_retained_depth=0,
                persistence_queue_depth=0,
                persistence_queue_capacity=1,
                persistence_retained_depth=0,
                low_priority_paused=False,
            )

    class _StubMarketWsWorker:
        def status_snapshot(self):
            return SimpleNamespace(
                last_result=None,
                subscription_count=0,
                last_message_at=None,
                last_error=None,
            )

    class _StubUserWsWorker:
        def status_snapshot(self):
            return SimpleNamespace(
                connected=False,
                subscription_count=0,
                last_message_at=None,
                last_result=None,
                last_error=None,
            )

    class _StubReconcileWorker:
        def status_snapshot(self):
            return SimpleNamespace(last_completed_at=None)

    class _StubPersistenceWorker:
        def snapshot(self):
            return SimpleNamespace(
                outbox_depth=0,
                outbox_retained_depth=0,
                outbox_dead_letter_depth=0,
                retried_events=0,
            )

    async def run() -> None:
        gamma = _StubGammaClient()
        discovery_worker = _StubDiscoveryWorker()
        runtime = SimpleNamespace(
            supervisor=_StubSupervisor(),
            strategy=_StubStrategy(),
            gamma_client=gamma,
            market_discovery_worker=discovery_worker,
            event_bus=_StubEventBus(),
            metrics=_StubMetrics(),
            market_ws_worker=_StubMarketWsWorker(),
            user_ws_worker=_StubUserWsWorker(),
            reconcile_worker=_StubReconcileWorker(),
            persistence_worker=_StubPersistenceWorker(),
        )

        await _run_market_discovery_scan(runtime)

        assert gamma.calls[0]["title_search"] == "fdv"
        assert len(discovery_worker.calls) == 1
        payload, source, trace_id = discovery_worker.calls[0]
        assert payload["markets"][0]["market_slug"] == "sample-market-a"
        assert source == "gamma.events"
        assert trace_id.startswith("market-discovery-")

    asyncio.run(run())
