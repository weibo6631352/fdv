from __future__ import annotations

from polymarket_trader.config import Settings


def test_settings_use_extension_module_naming() -> None:
    settings = Settings(_env_file=None, extension_module="tests.helpers.demo_extension")

    assert settings.extension_module == "tests.helpers.demo_extension"
    assert "strategy_module" not in settings.sanitized_dump()
