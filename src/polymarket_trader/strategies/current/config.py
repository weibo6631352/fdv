from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CurrentStrategyConfig:
    """当前策略的 Python 侧交易配置。

    这里保留的是交易阈值。
    市场 discovery 词、最终 universe 筛选条件直接写在
    `market_filter.py`，订阅保留规则直接写在 `subscription.py`。
    """

    # NO 侧允许主动买入的最高价格。
    # 当前策略只在盘口 ask 不高于这个价格时才会考虑入场。
    entry_no_price_max: Decimal = Decimal("0.60")
    # 持仓退出时使用的挂卖价格。
    # 当前策略统一按固定价格出场，不在这里做动态浮动。
    exit_no_price: Decimal = Decimal("0.70")
    # 入场前要求的最小可吃单深度，单位 USDC。
    # 深度不足时，即使价格满足，也不认为当前 market 适合开仓。
    min_liquidity_usdc: Decimal = Decimal("5")
    # 允许的最大买一卖一价差。
    # 如果 spread 过大，说明盘口不够紧，会直接放弃本轮入场。
    max_spread: Decimal | None = Decimal("0.10")


CURRENT_STRATEGY_CONFIG = CurrentStrategyConfig()


__all__ = ["CURRENT_STRATEGY_CONFIG", "CurrentStrategyConfig"]
