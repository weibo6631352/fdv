from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from fdv_trader.infra.polymarket.auth import PolymarketTradingClient
from fdv_trader.infra.polymarket.schemas import (
    ClobFillDTO,
    ClobOrderDTO,
    ClobOrderRequest,
    ClobOrderbookDTO,
    PolymarketRestClientBase,
    normalize_fill_payload,
    normalize_order_payload,
    normalize_orderbook_payload,
)


def _iter_mappings(payload: Any) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    if isinstance(payload, Mapping):
        for key in ("data", "items", "results", "rows", "orders", "fills"):
            value = payload.get(key)
            if isinstance(value, list):
                return tuple(item for item in value if isinstance(item, Mapping))
        return (payload,)
    return ()


def _normalize_request(request: ClobOrderRequest | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(request, ClobOrderRequest):
        return request.to_payload()
    return dict(request)


def _coerce_int(value: Any | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return int(Decimal(text))


class ClobClient(PolymarketRestClientBase):
    """Polymarket CLOB 读写适配器。

    这里负责把 CLOB 的订单簿、订单和成交响应转换成内部 DTO。
    下单语义在适配层里明确保留：BUY 的 amount 是花费金额，SELL 的 amount 是 shares。
    """

    def __init__(
        self,
        base_url: str = "https://clob.polymarket.com",
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
        headers: Mapping[str, str] | None = None,
        auth_client: PolymarketTradingClient | None = None,
        book_path: str = "/book",
        orders_path: str = "/orders",
        fills_path: str = "/fills",
        fee_rate_path: str = "/fee-rate",
    ) -> None:
        super().__init__(base_url, client=client, timeout_s=timeout_s, headers=headers)
        self._auth_client = auth_client
        self._book_path = book_path
        self._orders_path = orders_path
        self._fills_path = fills_path
        self._fee_rate_path = fee_rate_path

    @property
    def has_auth_client(self) -> bool:
        return self._auth_client is not None

    @property
    def default_wallet_address(self) -> str | None:
        if self._auth_client is None:
            return None
        return self._auth_client.get_address()

    async def get_orderbook(
        self,
        token_id: str,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> ClobOrderbookDTO:
        payload = await self.get_json(
            path or self._book_path,
            params={
                "token_id": token_id,
                **({"market_slug": market_slug} if market_slug is not None else {}),
                **({"condition_id": condition_id} if condition_id is not None else {}),
            },
            timeout_s=timeout_s,
            operation="clob.get_orderbook",
        )
        if isinstance(payload, Mapping):
            return normalize_orderbook_payload(
                payload,
                token_id=token_id,
                market_slug=market_slug,
                condition_id=condition_id,
            )
        raise TypeError("clob orderbook response is not a mapping")

    async def get_fee_rate(
        self,
        token_id: str,
        *,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> int:
        payload = await self.get_json(
            path or self._fee_rate_path,
            params={"token_id": token_id},
            timeout_s=timeout_s,
            operation="clob.get_fee_rate",
        )
        if not isinstance(payload, Mapping):
            raise TypeError("clob fee rate response is not a mapping")
        raw_fee_rate = payload.get("base_fee")
        if raw_fee_rate is None:
            raw_fee_rate = payload.get("baseFee")
        fee_rate_bps = _coerce_int(raw_fee_rate)
        if fee_rate_bps is None:
            raise TypeError("clob fee rate response missing base_fee")
        return fee_rate_bps

    async def list_open_orders(
        self,
        *,
        wallet_address: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[ClobOrderDTO, ...]:
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
            operation="clob.list_open_orders",
        )
        return tuple(normalize_order_payload(item) for item in _iter_mappings(payload))

    async def list_fills(
        self,
        *,
        wallet_address: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> tuple[ClobFillDTO, ...]:
        wallet_address = wallet_address or self.default_wallet_address
        params: dict[str, Any] = {}
        if wallet_address is not None:
            params["address"] = wallet_address
        if condition_id is not None:
            params["condition_id"] = condition_id
        if token_id is not None:
            params["token_id"] = token_id
        payload = await self.get_json(
            path or self._fills_path,
            params=params,
            headers=self._auth_headers("GET", path or self._fills_path),
            timeout_s=timeout_s,
            operation="clob.list_fills",
        )
        return tuple(normalize_fill_payload(item) for item in _iter_mappings(payload))

    async def create_order(
        self,
        request: ClobOrderRequest | Mapping[str, Any],
        *,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> ClobOrderDTO:
        payload = await self.post_json(
            path or self._orders_path,
            json_body=_normalize_request(request),
            timeout_s=timeout_s,
            operation="clob.create_order",
        )
        if isinstance(payload, Mapping):
            return normalize_order_payload(payload)
        raise TypeError("clob create order response is not a mapping")

    async def cancel_order(
        self,
        order_id: str,
        *,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> ClobOrderDTO:
        cancel_path = path or f"{self._orders_path.rstrip('/')}/{order_id}/cancel"
        payload = await self.post_json(
            cancel_path,
            json_body={"order_id": order_id},
            timeout_s=timeout_s,
            operation="clob.cancel_order",
        )
        if isinstance(payload, Mapping):
            return normalize_order_payload(payload)
        raise TypeError("clob cancel order response is not a mapping")

    async def replace_order(
        self,
        order_id: str,
        request: ClobOrderRequest | Mapping[str, Any],
        *,
        timeout_s: float | None = None,
        path: str | None = None,
    ) -> ClobOrderDTO:
        replace_path = path or f"{self._orders_path.rstrip('/')}/{order_id}"
        payload = await self.post_json(
            replace_path,
            json_body={"order_id": order_id, **_normalize_request(request)},
            timeout_s=timeout_s,
            operation="clob.replace_order",
        )
        if isinstance(payload, Mapping):
            return normalize_order_payload(payload)
        raise TypeError("clob replace order response is not a mapping")

    async def get_fills_for_market(
        self,
        token_id: str,
        *,
        timeout_s: float | None = None,
    ) -> tuple[ClobFillDTO, ...]:
        return await self.list_fills(token_id=token_id, timeout_s=timeout_s)

    def _auth_headers(self, method: str, request_path: str) -> Mapping[str, str] | None:
        if self._auth_client is None:
            return None
        return self._auth_client.build_l2_headers(method=method, request_path=request_path)


__all__ = ["ClobClient"]
