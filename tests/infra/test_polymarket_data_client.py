from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from fdv_trader.infra.polymarket.data_client import DataClient

pytestmark = pytest.mark.asyncio


async def test_data_client_list_positions_uses_official_query_params_and_maps_current_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/positions"
        return httpx.Response(
            200,
            json=[
                {
                    "proxyWallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                    "asset": "token-1",
                    "conditionId": "0x" + "1" * 64,
                    "size": 3,
                    "avgPrice": 0.5,
                    "initialValue": 1.5,
                    "slug": "token-fdv-500m",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=transport,
        trust_env=False,
    ) as client:
        data = DataClient(client=client)
        positions = await data.list_positions(
            user_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839",
            market_ids=("0x" + "1" * 64, "0x" + "2" * 64),
            limit=50,
            offset=10,
            sort_by="TOKENS",
            sort_direction="DESC",
        )

    request = requests[0]
    assert request.url.params.get("user") == "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    assert request.url.params.get("market") == ",".join(("0x" + "1" * 64, "0x" + "2" * 64))
    assert request.url.params.get("limit") == "50"
    assert request.url.params.get("offset") == "10"
    assert request.url.params.get("sortBy") == "TOKENS"
    assert request.url.params.get("sortDirection") == "DESC"
    assert len(positions) == 1
    position = positions[0]
    assert position.condition_id == "0x" + "1" * 64
    assert position.token_id == "token-1"
    assert position.shares == Decimal("3")
    assert position.cost_usdc == Decimal("1.5")
    assert position.market_slug == "token-fdv-500m"


async def test_data_client_list_trades_uses_official_query_params_and_maps_current_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/trades"
        return httpx.Response(
            200,
            json=[
                {
                    "proxyWallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                    "asset": "token-2",
                    "conditionId": "0x" + "2" * 64,
                    "side": "BUY",
                    "size": 4,
                    "price": 0.25,
                    "timestamp": 1700000000,
                    "slug": "token-fdv-1b",
                    "transactionHash": "0xabc",
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=transport,
        trust_env=False,
    ) as client:
        data = DataClient(client=client)
        trades = await data.list_trades(
            user_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839",
            market_ids=("0x" + "2" * 64,),
            side="BUY",
            taker_only=True,
            filter_type="CASH",
            filter_amount=Decimal("10"),
            limit=25,
            offset=0,
        )

    request = requests[0]
    assert request.url.params.get("user") == "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    assert request.url.params.get("market") == "0x" + "2" * 64
    assert request.url.params.get("side") == "BUY"
    assert request.url.params.get("takerOnly") == "true"
    assert request.url.params.get("filterType") == "CASH"
    assert request.url.params.get("filterAmount") == "10"
    assert request.url.params.get("limit") == "25"
    assert len(trades) == 1
    trade = trades[0]
    assert trade.trade_id == "0xabc"
    assert trade.condition_id == "0x" + "2" * 64
    assert trade.token_id == "token-2"
    assert trade.side == "BUY"
    assert trade.price == Decimal("0.25")
    assert trade.size_shares == Decimal("4")
    assert trade.notional_usdc == Decimal("1.00")
    assert trade.market_slug == "token-fdv-1b"
    assert trade.confirmed_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)


async def test_data_client_requires_user_and_rejects_partial_trade_filter() -> None:
    async with httpx.AsyncClient(
        base_url="https://data-api.polymarket.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
        trust_env=False,
    ) as client:
        data = DataClient(client=client)
        with pytest.raises(ValueError, match="user_address"):
            await data.list_positions()
        with pytest.raises(ValueError, match="filter_type and filter_amount"):
            await data.list_trades(
                user_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                filter_type="CASH",
            )
