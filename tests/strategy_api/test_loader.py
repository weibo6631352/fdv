from __future__ import annotations

from pathlib import Path
import sys

import pytest

from fdv_trader.strategy_api import (
    DEFAULT_STRATEGY_MODULE_PATH,
    StrategyLoadError,
    load_strategy,
    resolve_strategy_module_path,
)
import fdv_trader.strategies as strategies_pkg


def test_resolve_strategy_module_path_defaults_to_builtin_strategy() -> None:
    assert resolve_strategy_module_path() == DEFAULT_STRATEGY_MODULE_PATH
    assert resolve_strategy_module_path("   ") == DEFAULT_STRATEGY_MODULE_PATH
    assert resolve_strategy_module_path("fdv_default") == DEFAULT_STRATEGY_MODULE_PATH
    assert resolve_strategy_module_path("custom.module") == "custom.module"


def test_load_strategy_uses_build_strategy_with_config_path(tmp_path: Path) -> None:
    extension_root = _write_strategy_module(
        tmp_path,
        package_name="test_strategy",
        strategy_source="""
from fdv_trader.strategy_api.models import (
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)
from fdv_trader.domain.allocation import AllocationPlan


class TestStrategy:
    def __init__(self, config_path=None):
        self._config_path = config_path

    @property
    def spec(self):
        return StrategySpec(
            name="test_strategy",
            version="1",
            description=self._config_path or "",
        )

    def select_market(self, market):
        return UniverseDecision.include(reason="selected")

    def size_entry(self, context: StrategyContext):
        return EntrySizing(
            allocation_plan=AllocationPlan(
                trace_id=context.trace_id,
                total_budget_usdc=0,
                reason="sized",
            ),
            reason="sized",
        )

    def decide_entry(self, context: StrategyContext):
        return StrategyDecision.skip(reason="entry")

    def decide_exit(self, context: StrategyContext):
        return StrategyDecision.skip(reason="exit")

    def decide_recovery(self, context: StrategyContext):
        return RecoveryDecision(reason="recovery")


def build_strategy(config_path=None):
    return TestStrategy(config_path=config_path)
""",
    )
    _extend_strategies_path(extension_root)
    try:
        loaded = load_strategy("test_strategy", config_path="/tmp/strategy.yaml")
    finally:
        _cleanup_strategy_modules("test_strategy")
        _shrink_strategies_path(extension_root)

    assert loaded.name == "test_strategy"
    assert loaded.module_path == "fdv_trader.strategies.test_strategy.strategy"
    assert loaded.spec.description == "/tmp/strategy.yaml"


def test_load_strategy_raises_for_missing_exports(tmp_path: Path) -> None:
    extension_root = _write_strategy_module(
        tmp_path,
        package_name="broken_strategy",
        strategy_source="VALUE = 1\n",
    )
    _extend_strategies_path(extension_root)
    try:
        with pytest.raises(StrategyLoadError):
            load_strategy("broken_strategy")
    finally:
        _cleanup_strategy_modules("broken_strategy")
        _shrink_strategies_path(extension_root)


def test_load_strategy_loads_builtin_fdv_default() -> None:
    loaded = load_strategy()

    assert loaded.name == "fdv_default"
    assert loaded.module_path == DEFAULT_STRATEGY_MODULE_PATH


def _write_strategy_module(
    tmp_path: Path,
    *,
    package_name: str,
    strategy_source: str,
) -> Path:
    strategies_root = tmp_path / "fdv_trader" / "strategies"
    package_root = strategies_root / package_name
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "strategy.py").write_text(strategy_source.strip() + "\n", encoding="utf-8")
    return strategies_root


def _extend_strategies_path(path: Path) -> None:
    if str(path) not in strategies_pkg.__path__:
        strategies_pkg.__path__.append(str(path))


def _shrink_strategies_path(path: Path) -> None:
    try:
        strategies_pkg.__path__.remove(str(path))
    except ValueError:
        pass


def _cleanup_strategy_modules(package_name: str) -> None:
    sys.modules.pop(f"fdv_trader.strategies.{package_name}.strategy", None)
    sys.modules.pop(f"fdv_trader.strategies.{package_name}", None)
