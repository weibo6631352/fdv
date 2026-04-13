from __future__ import annotations

from fdv_trader.strategy_api.models import StrategySpec
from fdv_trader.strategy_api.config_loader import load_strategy_config
from fdv_trader.strategies.current.config import CurrentStrategyConfig
from fdv_trader.strategies.fdv_default.strategy import FDVDefaultStrategy


class CurrentStrategy(FDVDefaultStrategy):
    """Fixed runtime entrypoint for the single strategy implementation."""

    def __init__(self, config: CurrentStrategyConfig | None = None) -> None:
        super().__init__(config=config)
        self._spec = StrategySpec(
            name="current",
            version=self.spec.version,
            description="Fixed runtime strategy entrypoint",
            config_type=CurrentStrategyConfig,
            capabilities=self.spec.capabilities,
        )


def build_strategy(config_path: str | None = None) -> CurrentStrategy:
    config = load_strategy_config(CurrentStrategyConfig, config_path)
    return CurrentStrategy(config=config)
