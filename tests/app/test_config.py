from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from polymarket_trader.config import Settings


def test_settings_defaults_match_env_example(monkeypatch) -> None:
    for key in (
        "MAX_OPEN_ORDERS",
        "MARKET_SYNC_INTERVAL_SECONDS",
        "ORDER_RETRY_LIMIT",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.max_open_orders == 0
    assert settings.market_sync_interval_seconds == 60
    assert settings.order_retry_limit == 2


def test_settings_reject_removed_strategy_threshold_fields() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            portfolio_budget_usdc=Decimal("100"),
            max_order_usdc=Decimal("25"),
            max_market_usdc=Decimal("50"),
            max_total_usdc=Decimal("100"),
            min_liquidity_usdc=Decimal("5"),
        )
