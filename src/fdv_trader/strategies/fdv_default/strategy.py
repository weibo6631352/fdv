from __future__ import annotations

from fdv_trader.strategy_api.config_loader import load_strategy_config
from fdv_trader.strategy_api.models import StrategySpec
from fdv_trader.strategies.fdv_default.config import FDVDefaultStrategyConfig
from fdv_trader.strategies.template.strategy import TemplateStrategy


class FDVDefaultStrategy(TemplateStrategy):
    """Named reference wrapper around the original FDV strategy template."""

    def __init__(self, config: FDVDefaultStrategyConfig | None = None) -> None:
        super().__init__(config=config)
        self._spec = StrategySpec(
            name="fdv_default",
            version=self.spec.version,
            description="Original FDV strategy reference implementation",
            config_type=FDVDefaultStrategyConfig,
            capabilities=self.spec.capabilities,
        )


def build_strategy(config_path: str | None = None) -> FDVDefaultStrategy:
    config = load_strategy_config(FDVDefaultStrategyConfig, config_path)
    return FDVDefaultStrategy(config=config)
