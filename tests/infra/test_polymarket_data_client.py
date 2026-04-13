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


async def test_data_client_list_activity_uses_official_query_params_and_maps_current_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/activity"
        return httpx.Response(
            200,
            json=[
                {
                    "proxyWallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                    "timestamp": 1700000000,
                    "conditionId": "0x" + "3" * 64,
                    "type": "TRADE",
                    "size": 4,
                    "usdcSize": 1,
                    "transactionHash": "0xdef",
                    "price": 0.25,
                    "asset": "token-3",
                    "side": "BUY",
                    "outcomeIndex": 0,
                    "title": "Token FDV 2B",
                    "slug": "token-fdv-2b",
                    "icon": "https://example.com/icon.png",
                    "eventSlug": "event-fdv-2b",
                    "outcome": "Yes",
                    "name": "Trader",
                    "pseudonym": "trader-1",
                    "bio": "active trader",
                    "profileImage": "https://example.com/profile.png",
                    "profileImageOptimized": "https://example.com/profile-optimized.png",
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
        activities = await data.list_activity(
            user_address="0x56687bf447db6ffa42ffe2204a05edaa20f55839",
            market_ids=("0x" + "3" * 64,),
            activity_types=("TRADE",),
            start=1700000000,
            end=1700003600,
            sort_by="TIMESTAMP",
            sort_direction="DESC",
            side="BUY",
            limit=25,
            offset=10,
        )

    request = requests[0]
    assert request.url.params.get("user") == "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    assert request.url.params.get("market") == "0x" + "3" * 64
    assert request.url.params.get("type") == "TRADE"
    assert request.url.params.get("start") == "1700000000"
    assert request.url.params.get("end") == "1700003600"
    assert request.url.params.get("sortBy") == "TIMESTAMP"
    assert request.url.params.get("sortDirection") == "DESC"
    assert request.url.params.get("side") == "BUY"
    assert request.url.params.get("limit") == "25"
    assert request.url.params.get("offset") == "10"
    assert len(activities) == 1
    activity = activities[0]
    assert activity.proxy_wallet == "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    assert activity.condition_id == "0x" + "3" * 64
    assert activity.activity_type == "TRADE"
    assert activity.asset == "token-3"
    assert activity.side == "BUY"
    assert activity.market_slug == "token-fdv-2b"
    assert activity.timestamp == datetime.fromtimestamp(1700000000, tz=timezone.utc)


async def test_data_client_list_holders_uses_official_query_params_and_maps_current_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/holders"
        return httpx.Response(
            200,
            json=[
                {
                    "token": "token-4",
                    "holders": [
                        {
                            "proxyWallet": "0x56687bf447db6ffa42ffe2204a05edaa20f55839",
                            "bio": "active holder",
                            "asset": "token-4",
                            "pseudonym": "holder-1",
                            "amount": 42,
                            "displayUsernamePublic": True,
                            "outcomeIndex": 1,
                            "name": "Holder",
                            "profileImage": "https://example.com/profile.png",
                            "profileImageOptimized": "https://example.com/profile-optimized.png",
                        }
                    ],
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
        holders = await data.list_holders(
            market_ids=("0x" + "4" * 64,),
            limit=20,
            min_balance=2,
        )

    request = requests[0]
    assert request.url.params.get("market") == "0x" + "4" * 64
    assert request.url.params.get("limit") == "20"
    assert request.url.params.get("minBalance") == "2"
    assert len(holders) == 1
    market_holders = holders[0]
    assert market_holders.token_id == "token-4"
    assert len(market_holders.holders) == 1
    holder = market_holders.holders[0]
    assert holder.proxy_wallet == "0x56687bf447db6ffa42ffe2204a05edaa20f55839"
    assert holder.amount == Decimal("42")
    assert holder.display_username_public is True
    assert holder.profile_image_optimized == "https://example.com/profile-optimized.png"


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
        with pytest.raises(ValueError, match="user_address"):
            await data.list_activity()
