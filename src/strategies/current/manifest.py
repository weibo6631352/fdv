"""当前默认策略的 manifest。

框架的 strategy loader 会通过 manifest 找到策略模块路径和工厂函数。
"""

from __future__ import annotations

from polymarket_trader.extension_api import ExtensionManifest as StrategyManifest

from strategies.current.config import CurrentStrategyConfig
from strategies.current.strategy import build_strategy

# manifest 本身只描述“如何装配该策略”，不承载业务规则。
manifest = StrategyManifest(
    name="current",
    version="1",
    module_path="strategies.current",
    factory=build_strategy,
    config_type=CurrentStrategyConfig,
)
