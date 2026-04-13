from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from fdv_trader.domain.order import OrderStatus
from fdv_trader.infra.polymarket.clob_client import ClobClient

pytestmark = pytest.mark.asyncio


class _StubAuthClient:
    signature_type = 0

    def build_l2_headers(
        self,
        *,
        method: str,
        request_path: str,
        body: object | None = None,
    ) -> dict[str, str]:
        return {
            "X-Test-Method": method,
            "X-Test-Path": request_path,
        }


async def test_clob_client_list_open_orders_uses_sdk_path_params_and_paginates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/data/orders"
        cursor = request.url.params.get("next_cursor")
        if cursor == "MA==":
            payload = {
                "next_cursor": "MTAw",
                "data": [
                    {
                        "id": "order-1",
                        "status": "ORDER_STATUS_LIVE",
                        "market": "0x" + "1" * 64,
                        "asset_id": "token-1",
                        "side": "SELL",
                        "original_size": "5",
                        "size_matched": "2",
                        "price": "0.75",
                        "order_type": "GTC",
                        "created_at": 1700000000,
                    }
                ],
            }
        else:
            assert cursor == "MTAw"
            payload = {
                "next_cursor": "LTE=",
                "data": [
                    {
                        "id": "order-2",
                        "status": "ORDER_STATUS_LIVE",
                        "market": "0x" + "1" * 64,
                        "asset_id": "token-1",
                        "side": "BUY",
                        "original_size": "3",
                        "size_matched": "0",
                        "price": "0.51",
                        "order_type": "GTC",
                        "created_at": 1700000001,
                    }
                ],
            }
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://clob.polymarket.com",
        transport=transport,
        trust_env=False,
    ) as client:
        clob = ClobClient(client=client, auth_client=_StubAuthClient())
        orders = await clob.list_open_orders(
            condition_id="0x" + "1" * 64,
            token_id="token-1",
        )

    assert len(orders) == 2
    assert [request.url.params.get("market") for request in requests] == ["0x" + "1" * 64, "0x" + "1" * 64]
    assert [request.url.params.get("asset_id") for request in requests] == ["token-1", "token-1"]
    assert orders[0].condition_id == "0x" + "1" * 64
    assert orders[0].token_id == "token-1"
    assert orders[0].size_shares == Decimal("5")
    assert orders[0].filled_shares == Decimal("2")
    assert orders[0].remaining_shares == Decimal("3")
    assert orders[0].created_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)
    assert orders[0].to_order_record().status == OrderStatus.LIVE


async def test_clob_client_list_fills_uses_trade_ledger_path_and_maps_trade_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/data/trades"
        return httpx.Response(
            200,
            json={
                "next_cursor": "LTE=",
                "data": [
                    {
                        "id": "trade-123",
                        "taker_order_id": "order-123",
                        "market": "0x" + "2" * 64,
                        "asset_id": "token-2",
                        "side": "BUY",
                        "size": "4",
                        "price": "0.5",
                        "status": "TRADE_STATUS_CONFIRMED",
                        "match_time": "1700000000",
                        "maker_address": "0x1234567890123456789012345678901234567890",
                        "maker_orders": [],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://clob.polymarket.com",
        transport=transport,
        trust_env=False,
    ) as client:
        clob = ClobClient(client=client, auth_client=_StubAuthClient())
        fills = await clob.list_fills(
            condition_id="0x" + "2" * 64,
            token_id="token-2",
            maker_address="0x1234567890123456789012345678901234567890",
            after=1700000000,
        )

    assert len(fills) == 1
    request = requests[0]
    assert request.url.params.get("market") == "0x" + "2" * 64
    assert request.url.params.get("asset_id") == "token-2"
    assert request.url.params.get("maker_address") == "0x1234567890123456789012345678901234567890"
    assert request.url.params.get("after") == "1700000000"
    fill = fills[0]
    assert fill.trade_id == "trade-123"
    assert fill.order_id == "order-123"
    assert fill.condition_id == "0x" + "2" * 64
    assert fill.token_id == "token-2"
    assert fill.size_shares == Decimal("4")
    assert fill.status == "confirmed"
    assert fill.confirmed_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)
