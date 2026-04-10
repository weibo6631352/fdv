from __future__ import annotations

from fdv_trader.domain.market import Market


class MarketRegistry:
    def __init__(self) -> None:
        self._by_condition_id: dict[str, Market] = {}
        self._by_no_token_id: dict[str, Market] = {}

    def upsert(self, market: Market) -> None:
        self._by_condition_id[market.condition_id] = market
        self._by_no_token_id[market.no_token_id] = market

    def get_by_condition_id(self, condition_id: str) -> Market | None:
        return self._by_condition_id.get(condition_id)

