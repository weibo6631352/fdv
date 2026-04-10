from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from fdv_trader.infra.polymarket.auth import PolymarketTradingClient
from fdv_trader.infra.polymarket.schemas import (
    DataBalanceDTO,
    DataPositionDTO,
    DataTradeDTO,
    PolymarketRestClientBase,
    normalize_balance_payload,
    normalize_position_payload,
    normalize_trade_payload,
)


def _iter_mappings(payload: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results", "rows", "positions", "trades", "balances"):
            value = payload.get(key)
            if isinstance(value, list):
                return tuple(item for item in value if isinstance(item, Mapping))
        return (payload,)
    return ()


class DataClient(PolymarketRestClientBase):
    """Polymarket Data API 适配器。

    这里只负责把余额、持仓和成交原始响应转换成内部 DTO，避免上层直接依赖 Data API 字段名。
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
        balances_path: str = "/balances",
        orders_path: str = "/orders",
    ) -> None:
        super().__init__(base_url, client=client, timeout_s=timeout_s, headers=headers)
        self._auth_client = auth_client
        self._positions_path = positions_path
        self._trades_path = trades_path
        self._balances_path = balances_path
        self._orders_path = orders_path

    @property
    def has_auth_client(self) -> bool:
        return self._auth_client is not None

    @property
    def default_wallet_address(self) -> str | None:
        if self._auth_client is None:
            return None
        return self._auth_client.get_address()

    async def list_positions(
        self,
        *,
        wallet_address: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataPositionDTO, ...]:
        wallet_address = wallet_address or self.default_wallet_address
        params: dict[str, Any] = {}
        if wallet_address is not None:
            params["address"] = wallet_address
        if condition_id is not None:
            params["condition_id"] = condition_id
        if token_id is not None:
            params["token_id"] = token_id
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
        wallet_address: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[DataTradeDTO, ...]:
        wallet_address = wallet_address or self.default_wallet_address
        params: dict[str, Any] = {}
        if wallet_address is not None:
            params["address"] = wallet_address
        if condition_id is not None:
            params["condition_id"] = condition_id
        if token_id is not None:
            params["token_id"] = token_id
        payload = await self.get_json(
            path or self._trades_path,
            params=params,
            headers=self._auth_headers("GET", path or self._trades_path),
            timeout_s=timeout_s,
            operation="data.list_trades",
        )
        return tuple(normalize_trade_payload(item) for item in _iter_mappings(payload))

    async def get_balance(
        self,
        *,
        wallet_address: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> DataBalanceDTO:
        wallet_address = wallet_address or self.default_wallet_address
        params: dict[str, Any] = {}
        if wallet_address is not None:
            params["address"] = wallet_address
        payload = await self.get_json(
            path or self._balances_path,
            params=params,
            headers=self._auth_headers("GET", path or self._balances_path),
            timeout_s=timeout_s,
            operation="data.get_balance",
        )
        if isinstance(payload, Mapping):
            return normalize_balance_payload(payload)
        raise TypeError("data balance response is not a mapping")

    async def get_account_snapshot(
        self,
        *,
        wallet_address: str | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        # 账户快照只做结构化拼接，不把 Data API 的原始格式继续向上层暴露。
        positions = await self.list_positions(wallet_address=wallet_address, timeout_s=timeout_s)
        trades = await self.list_trades(wallet_address=wallet_address, timeout_s=timeout_s)
        balance = await self.get_balance(wallet_address=wallet_address, timeout_s=timeout_s)
        return {
            "balance": balance,
            "positions": positions,
            "trades": trades,
        }

    async def list_open_orders(
        self,
        *,
        wallet_address: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        wallet_address = wallet_address or self.default_wallet_address
        params: dict[str, Any] = {}
        if wallet_address is not None:
            params["address"] = wallet_address
        if condition_id is not None:
            params["condition_id"] = condition_id
        if token_id is not None:
            params["token_id"] = token_id
        payload = await self.get_json(
            path or self._orders_path,
            params=params,
            headers=self._auth_headers("GET", path or self._orders_path),
            timeout_s=timeout_s,
            operation="data.list_open_orders",
        )
        return tuple(_iter_mappings(payload))

    def _auth_headers(self, method: str, request_path: str) -> Mapping[str, str] | None:
        if self._auth_client is None:
            return None
        return self._auth_client.build_l2_headers(method=method, request_path=request_path)


__all__ = ["DataClient"]
