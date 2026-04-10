from __future__ import annotations

from decimal import Decimal

from fdv_trader.config import Settings
from fdv_trader.main import build_runtime


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
    assert runtime.market_service is not None
    assert runtime.market_ws_worker is not None
    assert runtime.user_ws_worker is not None
    assert runtime.strategy_service is not None
    assert runtime.trading_service is not None
    assert runtime.strategy_worker is not None
    assert runtime.account_state_store is not None
    assert runtime.order_executor is not None
    assert runtime.reconcile_service is not None
    assert runtime.reconcile_worker is not None
    assert runtime.strategy_worker.priority == "P0"
