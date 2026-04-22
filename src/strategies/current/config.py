"""当前默认策略的配置定义。

这个文件只负责描述“策略自己关心的业务参数”，不负责框架级配置。
二次开发时如果只是替换筛选词、价格阈值、流动性门槛，通常从这里开始改。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polymarket_trader.extension_api import load_extension_config


@dataclass(frozen=True, slots=True)
class CurrentStrategyConfig:
    """当前策略的静态配置。

    字段说明：
        entry_no_price_max:
            NO 侧允许主动买入的最高价格。盘口 ask 高于这个值时，
            策略会直接跳过本轮入场。
        exit_no_price:
            退出时使用的目标挂卖价格。
        min_liquidity_usdc:
            允许入场前要求达到的最小盘口深度，单位是 USDC。
        max_spread:
            允许的最大买一卖一价差；为 ``None`` 表示不限制。
        discovery_title_searches:
            远端 discovery 的标题搜索词。框架会按这些词去 Gamma 做粗筛。
        required_category_tokens:
            本地 universe 精筛时必须命中的分类 token。
        required_event_tokens:
            本地 universe 精筛时必须命中的 event 级 token。
        required_target_tokens:
            本地 universe 精筛时必须命中的 market 文本 token。
    """

    entry_no_price_max: Decimal = Decimal("0.60")
    exit_no_price: Decimal = Decimal("0.70")
    min_liquidity_usdc: Decimal = Decimal("5")
    max_spread: Decimal | None = Decimal("0.10")
    discovery_title_searches: tuple[str, ...] = ("fdv", "fully diluted valuation")
    required_category_tokens: tuple[str, ...] = ("crypto", "cryptocurrency")
    required_event_tokens: tuple[str, ...] = ("fdv",)
    required_target_tokens: tuple[str, ...] = ("500m",)


def default_strategy_config() -> CurrentStrategyConfig:
    """返回内置默认配置。

    返回：
        一份可直接用于生产装配的 ``CurrentStrategyConfig``。
    """

    return CurrentStrategyConfig()


def load_current_strategy_config(config_path: str | None) -> CurrentStrategyConfig:
    """从外部配置文件加载当前策略配置。

    参数：
        config_path:
            外部配置文件路径。支持 ``json`` / ``toml``。如果为 ``None``，
            或者调用方没有提供配置文件，则退回默认配置。

    返回：
        解析后的 ``CurrentStrategyConfig``。
    """

    return load_extension_config(CurrentStrategyConfig, config_path) or default_strategy_config()
