from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
from types import ModuleType

from fdv_trader.strategy_api.errors import StrategyLoadError
from fdv_trader.strategy_api.interfaces import StrategyModule
from fdv_trader.strategy_api.models import StrategySpec


@dataclass(frozen=True, slots=True)
class LoadedStrategy:
    name: str
    module_path: str
    strategy: StrategyModule
    spec: StrategySpec


def resolve_strategy_module_path(active_strategy: str) -> str:
    normalized = active_strategy.strip()
    if not normalized:
        raise StrategyLoadError("active strategy name cannot be blank")
    if "." in normalized:
        return normalized
    return f"fdv_trader.strategies.{normalized}.strategy"


def load_strategy(
    active_strategy: str,
    *,
    config_path: str | None = None,
) -> LoadedStrategy:
    module_path = resolve_strategy_module_path(active_strategy)
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise StrategyLoadError(
            f"failed to import strategy module '{module_path}'"
        ) from exc

    strategy = _load_strategy_from_module(module, config_path=config_path)
    if not isinstance(strategy, StrategyModule):
        raise StrategyLoadError(
            f"module '{module_path}' did not provide a valid StrategyModule"
        )
    return LoadedStrategy(
        name=strategy.spec.name,
        module_path=module_path,
        strategy=strategy,
        spec=strategy.spec,
    )


def _load_strategy_from_module(
    module: ModuleType,
    *,
    config_path: str | None,
) -> StrategyModule:
    builder = getattr(module, "build_strategy", None)
    if callable(builder):
        return _invoke_builder(builder, config_path=config_path)

    exported = getattr(module, "strategy", None)
    if exported is not None:
        return exported
    exported = getattr(module, "STRATEGY", None)
    if exported is not None:
        return exported

    raise StrategyLoadError(
        f"module '{module.__name__}' must export build_strategy(), strategy, or STRATEGY"
    )


def _invoke_builder(builder: object, *, config_path: str | None) -> StrategyModule:
    signature = inspect.signature(builder)
    parameters = signature.parameters
    if "config_path" in parameters:
        return builder(config_path=config_path)  # type: ignore[misc]
    if not parameters:
        return builder()  # type: ignore[misc]
    raise StrategyLoadError(
        "build_strategy() must accept either no arguments or a 'config_path' keyword argument"
    )
