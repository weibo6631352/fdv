from __future__ import annotations

from decimal import Decimal

# 当前策略的交易阈值直接写在 Python 常量里。
# 二次开发如果只想调整入场/退出/盘口门槛，优先改这个文件。

# NO 侧允许主动买入的最高价格。
# 当前策略只在盘口 ask 不高于这个价格时才会考虑入场。
ENTRY_NO_PRICE_MAX = Decimal("0.60")

# 持仓退出时使用的挂卖价格。
# 当前策略统一按固定价格出场，不在这里做动态浮动。
EXIT_NO_PRICE = Decimal("0.70")

# 入场前要求的最小可吃单深度，单位 USDC。
# 深度不足时，即使价格满足，也不认为当前 market 适合开仓。
MIN_LIQUIDITY_USDC = Decimal("5")

# 允许的最大买一卖一价差。
# 如果 spread 过大，说明盘口不够紧，会直接放弃本轮入场。
MAX_SPREAD: Decimal | None = Decimal("0.10")


__all__ = [
    "ENTRY_NO_PRICE_MAX",
    "EXIT_NO_PRICE",
    "MIN_LIQUIDITY_USDC",
    "MAX_SPREAD",
]
