from __future__ import annotations

from decimal import Decimal

from fdv_trader.config import Settings


def test_settings_defaults_match_env_example(monkeypatch) -> None:
    for key in (
        "MIN_LIQUIDITY_USDC",
        "MAX_SPREAD",
        "MAX_OPEN_ORDERS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.min_liquidity_usdc == Decimal("5")
    assert settings.max_spread == Decimal("0.10")
    assert settings.max_open_orders == 0
