from __future__ import annotations

from polymarket_trader.domain.market import Market
from polymarket_trader.strategy_api.models import DiscoveryEndpoint, DiscoveryQuery, UniverseDecision

# 当前策略的 discovery / universe 词直接写死在这里。
# 这样二次开发改市场筛选时，只需要盯这个文件，不必来回跳配置。
DISCOVERY_TITLE_SEARCHES: tuple[str, ...] = ("fdv", "fully diluted valuation")
REQUIRED_CATEGORY_TOKENS: frozenset[str] = frozenset(("crypto", "cryptocurrency"))
REQUIRED_EVENT_TOKENS: tuple[str, ...] = ("fdv",)
REQUIRED_TARGET_TOKENS: tuple[str, ...] = ("500m",)


def build_discovery_queries() -> tuple[DiscoveryQuery, ...]:
    """声明远端 discovery 查询。

    这里放的是“去 Gamma 扫什么”的业务语义，不是框架级配置。
    二次开发时通常只需要改本文件顶部这些常量。
    """

    queries: list[DiscoveryQuery] = []
    for title_search in DISCOVERY_TITLE_SEARCHES:
        if not title_search.strip():
            continue
        queries.append(
            DiscoveryQuery(
                endpoint=DiscoveryEndpoint.EVENTS_KEYSET,
                params={
                    "active": True,
                    "closed": False,
                    "title_search": title_search,
                    "limit": 100,
                    "order": "volume",
                    "ascending": False,
                },
                max_pages=1,
            )
        )
    return tuple(queries)


def select_market(market: Market) -> UniverseDecision:
    """做最终市场筛选。

    远端 discovery 只负责缩小扫描范围，真正是否纳入当前策略 universe，
    仍然在这里统一判断。
    """

    category_tokens = _normalized_tokens(" ".join(_non_empty(market.category, *market.tags)))
    event_tokens = _normalized_tokens(market.event_title)
    market_tokens = _normalized_tokens(
        " ".join(_non_empty(market.market_question, market.market_name, market.market_slug))
    )

    has_category = bool(REQUIRED_CATEGORY_TOKENS & category_tokens)
    has_event = all(token in event_tokens for token in REQUIRED_EVENT_TOKENS)
    has_target = all(token in market_tokens for token in REQUIRED_TARGET_TOKENS)
    if has_category and has_event and has_target:
        return UniverseDecision.include(reason="selected_by_strategy")
    return UniverseDecision.exclude(reason="market_out_of_universe")


def _non_empty(*values: str | None) -> tuple[str, ...]:
    return tuple(value for value in values if value)


def _normalized_tokens(text: str | None) -> set[str]:
    """把常见表达归一化成稳定 token，减少业务判断里的文本噪声。"""

    if not text:
        return set()
    normalized = (
        text.lower()
        .replace("$500 million", "500m")
        .replace("500 million", "500m")
        .replace("500,000,000", "500m")
        .replace("$500m", "500m")
        .replace("500 m", "500m")
        .replace("fully diluted valuation", "fdv")
    )
    parts: list[str] = []
    current: list[str] = []
    for char in normalized:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    return {part for part in parts if part}
