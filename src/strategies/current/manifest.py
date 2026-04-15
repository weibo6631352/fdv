"""当前默认策略的 manifest。

框架的 strategy loader 会通过 manifest 找到策略模块路径和工厂函数。
"""

from __future__ import annotations

from strategy_sdk import StrategyManifest

from strategies.current.strategy import build_strategy

# manifest 本身只描述“如何装配该策略”，不承载业务规则。
manifest = StrategyManifest(
    module_path="strategies.current",
    factory=build_strategy,
)
