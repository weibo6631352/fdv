from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from polymarket_trader.domain.constants import ENTRY_NO_PRICE_MAX, EXIT_NO_PRICE


@dataclass(frozen=True, slots=True)
class CurrentStrategyConfig:
    """当前策略的 Python 侧业务配置。

    二次开发时优先只改这个文件，不再通过 `.env`、`.json`、`.toml`
    给策略本身传参。这样业务同学只需要盯住 `strategies/current/`
    目录里的少数几个文件即可。
    """

    # 远端 discovery 先用官方 title_search 把扫描范围收窄。
    discovery_title_searches: tuple[str, ...] = ("fdv", "fully diluted valuation")
    # 最终 universe 判断要求分类必须是 Crypto 相关。
    required_category_tokens: tuple[str, ...] = ("crypto", "cryptocurrency")
    # event 标题里至少要能识别出 FDV 语义。
    required_event_tokens: tuple[str, ...] = ("fdv",)
    # market 文本里必须出现目标阈值。
    required_target_tokens: tuple[str, ...] = ("500m",)
    # 下面这些属于当前策略的交易语义，不再放进框架 `.env`。
    entry_no_price_max: Decimal = ENTRY_NO_PRICE_MAX
    exit_no_price: Decimal = EXIT_NO_PRICE
    min_liquidity_usdc: Decimal = Decimal("5")
    max_spread: Decimal | None = Decimal("0.10")
    # 当 market 被策略排除后，若账户里还有仓位或挂单，就继续保留订阅。
    retain_filtered_market_tracking: bool = True


CURRENT_STRATEGY_CONFIG = CurrentStrategyConfig()


__all__ = ["CURRENT_STRATEGY_CONFIG", "CurrentStrategyConfig"]
