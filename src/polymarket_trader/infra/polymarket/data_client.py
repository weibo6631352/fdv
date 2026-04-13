from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from polymarket_trader.infra.polymarket.auth import PolymarketTradingClient
from polymarket_trader.infra.polymarket.schemas import (
    DataActivityDTO,
    DataClosedPositionDTO,
    DataMarketHoldersDTO,
    DataMarketPositionsDTO,
    DataPositionDTO,
    DataTradeDTO,
    DataUserValueDTO,
    PolymarketRestClientBase,
    normalize_activity_payload,
    normalize_closed_position_payload,
    normalize_market_holders_payload,
    normalize_market_positions_payload,
    normalize_position_payload,
    normalize_trade_payload,
    normalize_user_value_payload,
)


def _iter_mappings(payload: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results", "rows", "positions", "trades"):
            value = payload.get(key)
            if isinstance(value, list):
                return tuple(item for item in value if isinstance(item, Mapping))
        return (payload,)
    return ()


class DataClient(PolymarketRestClientBase):
    """Polymarket Data API 适配器。

    这里只负责把持仓、成交和只读账户查询原始响应转换成内部 DTO，
    避免上层直接依赖 Data API 字段名。
    """

    def __init__(
        self,
        base_url: str = "https://data-api.polymarket.com",
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
        headers: Mapping[str, str] | None = None,
        auth_client: PolymarketTradingClient | None = None,
        positions_path: str = "/positions",
        trades_path: str = "/trades",
        activity_path: str = "/activity",
        holders_path: str = "/holders",
        market_positions_path: str = "/market-positions",
        closed_positions_path: str = "/closed-positions",
        value_path: str = "/value",
    ) -> None:
        super().__init__(base_url, client=client, timeout_s=timeout_s, headers=headers)
        self._auth_client = auth_client
        self._positions_path = positions_path
        self._trades_path = trades_path
        self._activity_path = activity_path
        self._holders_path = holders_path
        self._market_positions_path = market_positions_path
        self._closed_positions_path = closed_positions_path
        self._value_path = value_path

    @property
    def has_auth_client(self) -> bool:
        return self._auth_client is not None

    @property
    def default_wallet_address(self) -> str | None:
        if self._auth_client is None:
            return None
        return self._auth_client.get_address()

    @property
    def default_user_address(self) -> str | None:
        return self.default_wallet_address

    def _resolve_user_address(self, user_address: str | None) -> str:
        resolved = user_address or self.default_user_address
        if resolved is None:
            raise ValueError("DataClient requires user_address or an auth client with a default address")
        return resolved

    def _build_market_params(
        self,
        *,
        market_ids: tuple[str, ...] | None = None,
        event_ids: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        if market_ids and event_ids:
            raise ValueError("market_ids and event_ids are mutually exclusive")
        params: dict[str, Any] = {}
        if market_ids:
            params["market"] = ",".join(market_ids)
        if event_ids:
            params["eventId"] = ",".join(str(event_id) for event_id in event_ids)
        return params

    async def list_positions(
        self,
        *,
        user_address: str | None = None,
        market_ids: tuple[str, ...] | None = None,
        event_ids: tuple[int, ...] | None = None,
        size_threshold: Decimal | None = None,
        redeemable: bool | None = None,
        mergeable: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
        title: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataPositionDTO, ...]:
        params = {
            "user": self._resolve_user_address(user_address),
            **self._build_market_params(market_ids=market_ids, event_ids=event_ids),
        }
        if size_threshold is not None:
            params["sizeThreshold"] = str(size_threshold)
        if redeemable is not None:
            params["redeemable"] = redeemable
        if mergeable is not None:
            params["mergeable"] = mergeable
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if sort_by is not None:
            params["sortBy"] = sort_by
        if sort_direction is not None:
            params["sortDirection"] = sort_direction
        if title is not None:
            params["title"] = title
        payload = await self.get_json(
            path or self._positions_path,
            params=params,
            headers=self._auth_headers("GET", path or self._positions_path),
            timeout_s=timeout_s,
            operation="data.list_positions",
        )
        return tuple(normalize_position_payload(item) for item in _iter_mappings(payload))

    async def list_trades(
        self,
        *,
        user_address: str | None = None,
        market_ids: tuple[str, ...] | None = None,
        event_ids: tuple[int, ...] | None = None,
        side: str | None = None,
        taker_only: bool | None = None,
        filter_type: str | None = None,
        filter_amount: Decimal | None = None,
        limit: int | None = None,
        offset: int | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataTradeDTO, ...]:
        if (filter_type is None) != (filter_amount is None):
            raise ValueError("filter_type and filter_amount must be provided together")
        params = {
            "user": self._resolve_user_address(user_address),
            **self._build_market_params(market_ids=market_ids, event_ids=event_ids),
        }
        if side is not None:
            params["side"] = side
        if taker_only is not None:
            params["takerOnly"] = taker_only
        if filter_type is not None:
            params["filterType"] = filter_type
            params["filterAmount"] = str(filter_amount)
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        payload = await self.get_json(
            path or self._trades_path,
            params=params,
            headers=self._auth_headers("GET", path or self._trades_path),
            timeout_s=timeout_s,
            operation="data.list_trades",
        )
        return tuple(normalize_trade_payload(item) for item in _iter_mappings(payload))

    async def list_activity(
        self,
        *,
        user_address: str | None = None,
        market_ids: tuple[str, ...] | None = None,
        event_ids: tuple[int, ...] | None = None,
        activity_types: tuple[str, ...] | None = None,
        start: int | None = None,
        end: int | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
        side: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataActivityDTO, ...]:
        params = {
            "user": self._resolve_user_address(user_address),
            **self._build_market_params(market_ids=market_ids, event_ids=event_ids),
        }
        if activity_types:
            params["type"] = ",".join(activity_types)
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if sort_by is not None:
            params["sortBy"] = sort_by
        if sort_direction is not None:
            params["sortDirection"] = sort_direction
        if side is not None:
            params["side"] = side
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        activity_path = path or self._activity_path
        payload = await self.get_json(
            activity_path,
            params=params,
            headers=self._auth_headers("GET", activity_path),
            timeout_s=timeout_s,
            operation="data.list_activity",
        )
        return tuple(normalize_activity_payload(item) for item in _iter_mappings(payload))

    async def list_holders(
        self,
        *,
        market_ids: tuple[str, ...],
        limit: int | None = None,
        min_balance: int | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataMarketHoldersDTO, ...]:
        params = self._build_market_params(market_ids=market_ids)
        if limit is not None:
            params["limit"] = limit
        if min_balance is not None:
            params["minBalance"] = min_balance
        holders_path = path or self._holders_path
        payload = await self.get_json(
            holders_path,
            params=params,
            headers=self._auth_headers("GET", holders_path),
            timeout_s=timeout_s,
            operation="data.list_holders",
        )
        return tuple(normalize_market_holders_payload(item) for item in _iter_mappings(payload))

    async def list_market_positions(
        self,
        *,
        condition_id: str,
        user_address: str | None = None,
        status: str | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataMarketPositionsDTO, ...]:
        params: dict[str, Any] = {"market": condition_id}
        if user_address is not None:
            params["user"] = user_address
        if status is not None:
            params["status"] = status
        if sort_by is not None:
            params["sortBy"] = sort_by
        if sort_direction is not None:
            params["sortDirection"] = sort_direction
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        market_positions_path = path or self._market_positions_path
        payload = await self.get_json(
            market_positions_path,
            params=params,
            headers=self._auth_headers("GET", market_positions_path),
            timeout_s=timeout_s,
            operation="data.list_market_positions",
        )
        return tuple(normalize_market_positions_payload(item) for item in _iter_mappings(payload))

    async def list_closed_positions(
        self,
        *,
        user_address: str | None = None,
        market_ids: tuple[str, ...] | None = None,
        event_ids: tuple[int, ...] | None = None,
        title: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataClosedPositionDTO, ...]:
        params = {
            "user": self._resolve_user_address(user_address),
            **self._build_market_params(market_ids=market_ids, event_ids=event_ids),
        }
        if title is not None:
            params["title"] = title
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        if sort_by is not None:
            params["sortBy"] = sort_by
        if sort_direction is not None:
            params["sortDirection"] = sort_direction
        closed_positions_path = path or self._closed_positions_path
        payload = await self.get_json(
            closed_positions_path,
            params=params,
            headers=self._auth_headers("GET", closed_positions_path),
            timeout_s=timeout_s,
            operation="data.list_closed_positions",
        )
        return tuple(normalize_closed_position_payload(item) for item in _iter_mappings(payload))

    async def get_user_value(
        self,
        *,
        user_address: str | None = None,
        market_ids: tuple[str, ...] | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> DataUserValueDTO:
        params = {
            "user": self._resolve_user_address(user_address),
            **self._build_market_params(market_ids=market_ids),
        }
        value_path = path or self._value_path
        payload = await self.get_json(
            value_path,
            params=params,
            headers=self._auth_headers("GET", value_path),
            timeout_s=timeout_s,
            operation="data.get_user_value",
        )
        items = _iter_mappings(payload)
        if not items:
            raise TypeError("data user value response missing items")
        return normalize_user_value_payload(items[0])

    def _auth_headers(self, method: str, request_path: str) -> Mapping[str, str] | None:
        if self._auth_client is None:
            return None
        return self._auth_client.build_l2_headers(method=method, request_path=request_path)


__all__ = ["DataClient"]
