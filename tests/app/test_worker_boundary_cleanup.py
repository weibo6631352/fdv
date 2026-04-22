from __future__ import annotations

from pathlib import Path


def test_reconcile_worker_does_not_import_polymarket_infra_clients() -> None:
    source = Path("src/polymarket_trader/workers/reconcile_worker.py").read_text(encoding="utf-8")

    assert "polymarket_trader.infra.polymarket" not in source
    assert "GammaClient" not in source
    assert "ClobClient" not in source
    assert "DataClient" not in source
    assert "PolymarketTradingClient" not in source


def test_ws_workers_delegate_external_payload_parsing_to_adapters() -> None:
    market_source = Path("src/polymarket_trader/workers/market_ws_worker.py").read_text(
        encoding="utf-8"
    )
    user_worker_source = Path("src/polymarket_trader/workers/user_ws_worker.py").read_text(
        encoding="utf-8"
    )
    user_projection_source = Path("src/polymarket_trader/workers/user_ws_projection.py").read_text(
        encoding="utf-8"
    )

    assert "market_ws_adapter" in market_source
    assert "user_ws_adapter" not in user_worker_source
    assert "user_ws_adapter" in user_projection_source
    assert "def _parse_levels" not in market_source
    assert "def _iter_order_snapshots" not in user_worker_source
