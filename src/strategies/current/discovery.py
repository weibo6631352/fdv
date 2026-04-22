"""当前策略的远端 discovery 查询定义。

这里描述“去 Gamma 扫什么”，目标是先把远端扫描范围压小，
减少后续本地分类和 universe 精筛的无效工作。
"""

from __future__ import annotations

from polymarket_trader.extension_api import DiscoveryEndpoint, DiscoveryQuery

from strategies.current.config import CurrentStrategyConfig


def build_discovery_queries(config: CurrentStrategyConfig) -> tuple[DiscoveryQuery, ...]:
    """根据策略配置构造远端扫描请求。

    参数：
        config:
            当前策略配置。这里只使用其中和 discovery 相关的字段，
            比如 ``discovery_title_searches``。

    返回：
        一组 ``DiscoveryQuery``。框架会逐条执行这些查询，
        并把返回的 markets 交给 ``MarketDiscoveryWorker``。

    说明：
        这里的 ``params`` 会基本原样透传到 Gamma API。
        框架只负责补齐分页和过滤 ``None`` 值，不重新解释业务语义。
    """

    queries: list[DiscoveryQuery] = []
    for title_search in config.discovery_title_searches:
        # 允许配置里出现空字符串，运行时这里统一跳过，避免发出无意义查询。
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
