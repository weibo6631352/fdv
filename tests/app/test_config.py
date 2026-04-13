from __future__ import annotations

from decimal import Decimal

import pytest

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


def test_settings_expose_active_strategy_defaults(monkeypatch) -> None:
    for key in ("ACTIVE_STRATEGY", "STRATEGY_CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.active_strategy == "fdv_default"
    assert settings.strategy_config_path is None


def test_settings_normalize_strategy_fields(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_STRATEGY", "  custom_strategy  ")
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", "  /tmp/strategy.yaml  ")

    settings = Settings(_env_file=None)

    assert settings.active_strategy == "custom_strategy"
    assert settings.strategy_config_path == "/tmp/strategy.yaml"


def test_settings_reject_blank_active_strategy(monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_STRATEGY", "   ")

    with pytest.raises(Exception):
        Settings(_env_file=None)
