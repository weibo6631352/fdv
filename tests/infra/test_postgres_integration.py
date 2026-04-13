from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from fdv_trader.app.admin_service import AdminService
from fdv_trader.config import load_settings
from fdv_trader.infra.db import Base, DatabasePersistenceRepository, build_session_factory, initialize_database
from fdv_trader.main import _check_database_connection
from fdv_trader.runtime.account_state import AccountStateStore
from fdv_trader.runtime.registry import MarketRegistry

pytestmark = pytest.mark.asyncio


def _integration_database_url() -> str | None:
    if explicit := os.environ.get("FDV_TEST_POSTGRES_DSN"):
        return explicit
    try:
        settings = load_settings()
    except Exception:
        return None
    if settings.database_password is None or not settings.database_password.get_secret_value().strip():
        return None
    return settings.database_url


async def _truncate_all_tables(session_factory: async_sessionmaker) -> None:
    engine = getattr(session_factory, "kw", {}).get("bind")
    if engine is None:
        return
    table_names = [table.name for table in reversed(Base.metadata.sorted_tables)]
    if not table_names:
        return
    joined = ", ".join(f'"{table_name}"' for table_name in table_names)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def postgres_session_factory() -> async_sessionmaker:
    database_url = _integration_database_url()
    if database_url is None:
        pytest.skip("PostgreSQL integration DSN is not configured")

    await initialize_database(database_url)
    session_factory = build_session_factory(database_url)
    if not await _check_database_connection(session_factory):
        bind = getattr(session_factory, "kw", {}).get("bind")
        if bind is not None:
            await bind.dispose()
        pytest.skip("PostgreSQL integration database is unavailable")

    await _truncate_all_tables(session_factory)
    try:
        yield session_factory
    finally:
        await _truncate_all_tables(session_factory)
        bind = getattr(session_factory, "kw", {}).get("bind")
        if bind is not None:
            await bind.dispose()


async def test_initialize_database_creates_expected_tables(
    postgres_session_factory: async_sessionmaker,
) -> None:
    engine = getattr(postgres_session_factory, "kw", {}).get("bind")
    assert engine is not None

    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        )
        table_names = tuple(rows.scalars().all())

    assert table_names == (
        "allocations",
        "audit_events",
        "fills",
        "markets",
        "orderbook_snapshots",
        "orders",
        "outbox_events",
        "positions",
    )


async def test_persistence_repository_and_admin_service_round_trip(
    postgres_session_factory: async_sessionmaker,
) -> None:
    repository = DatabasePersistenceRepository(postgres_session_factory)
    await repository.save_market_snapshot(
        {
            "trace_id": "trace-market",
            "source": "integration_test",
            "condition_id": "condition-500m",
            "market_slug": "token-fdv-500m",
            "no_token_id": "no-token",
            "yes_token_id": "yes-token",
            "event_id": "event-1",
            "event_title": "Token FDV above 500M in 2026?",
            "event_slug": "token-fdv",
            "tick_size": "0.01",
            "min_order_size": "1",
            "neg_risk": False,
            "fees_enabled": True,
            "maker_base_fee_bps": 0,
            "taker_base_fee_bps": 100,
            "fee_rate_bps": 125,
            "fee_rate_updated_at": "2026-01-01T12:02:00+00:00",
            "category": "Crypto",
            "tags": ["crypto", "fdv"],
            "matched_keywords": ["crypto", "fdv", "500m"],
            "trading_status": "eligible",
        }
    )
    await repository.save_fill(
        {
            "trace_id": "trace-fill",
            "event_type": "trade_confirmed",
            "event_id": "fill-1",
            "market_slug": "token-fdv-500m",
            "condition_id": "condition-500m",
            "token_id": "no-token",
            "order_id": "sell-1",
            "trade_id": "trade-1",
            "side": "SELL",
            "price": "0.70",
            "size": "3",
            "notional_usdc": "2.10",
            "status": "confirmed",
        }
    )

    runtime = SimpleNamespace(
        db_session_factory=postgres_session_factory,
        registry=MarketRegistry(),
        account_state_store=AccountStateStore(),
    )
    service = AdminService(runtime=runtime)

    markets = await service.list_markets(limit=10, offset=0)
    fills = await service.list_fills(limit=10, offset=0)

    assert markets["total"] == 1
    assert markets["items"][0]["market"]["market_slug"] == "token-fdv-500m"
    assert markets["items"][0]["market"]["trading_status"] == "eligible"
    assert markets["items"][0]["market"]["fees"]["enabled"] is True
    assert markets["items"][0]["market"]["fees"]["taker_base_fee_bps"] == 100
    assert markets["items"][0]["market"]["fees"]["fee_rate_bps"] == 125

    assert fills["total"] == 1
    assert fills["items"][0]["trace_id"] == "trace-fill"
    assert fills["items"][0]["trade_id"] == "trade-1"
    assert fills["items"][0]["status"] == "confirmed"
