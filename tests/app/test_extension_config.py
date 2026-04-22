from __future__ import annotations

from polymarket_trader.config import Settings


def test_settings_use_extension_module_naming() -> None:
    settings = Settings(extension_module="strategies.current")

    assert settings.extension_module == "strategies.current"
    assert "strategy_module" not in settings.sanitized_dump()
