from __future__ import annotations

import httpx
import pytest

from polymarket_trader.infra.polymarket.gamma_client import GammaClient

pytestmark = pytest.mark.asyncio


async def test_gamma_client_get_public_profile_uses_official_endpoint_and_query_param() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/public-profile"
        return httpx.Response(
            200,
            json={
                "createdAt": "2026-01-01T12:00:00Z",
                "proxyWallet": "0x1111111111111111111111111111111111111111",
                "profileImage": "https://example.com/avatar.png",
                "displayUsernamePublic": True,
                "bio": "market watcher",
                "pseudonym": "market-watch-001",
                "name": "Market Watcher",
                "users": [
                    {
                        "id": "user-1",
                        "creator": True,
                        "mod": False,
                    }
                ],
                "xUsername": "marketwatcher",
                "verifiedBadge": True,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://gamma-api.polymarket.com",
        transport=transport,
        trust_env=False,
    ) as client:
        gamma = GammaClient(client=client)
        profile = await gamma.get_public_profile("0x1111111111111111111111111111111111111111")

    request = requests[0]
    assert request.url.params.get("address") == "0x1111111111111111111111111111111111111111"
    assert profile.proxy_wallet == "0x1111111111111111111111111111111111111111"
    assert profile.profile_image == "https://example.com/avatar.png"
    assert profile.name == "Market Watcher"
    assert profile.x_username == "marketwatcher"
    assert profile.verified_badge is True


async def test_gamma_client_search_public_profiles_uses_official_endpoint_and_maps_profiles() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/public-search"
        return httpx.Response(
            200,
            json={
                "profiles": [
                    {
                        "id": "profile-1",
                        "name": "Market Watcher",
                        "pseudonym": "market-watch-001",
                        "displayUsernamePublic": True,
                        "profileImage": "https://example.com/profile.png",
                        "profileImageOptimized": {
                            "imageUrlOptimized": "https://example.com/profile-optimized.png",
                        },
                        "bio": "market watcher",
                        "proxyWallet": "0x1111111111111111111111111111111111111111",
                        "createdAt": "2026-01-01T12:00:00Z",
                        "updatedAt": "2026-01-02T12:00:00Z",
                        "walletActivated": True,
                        "isCloseOnly": False,
                        "isCertReq": False,
                    }
                ],
                "pagination": {
                    "hasMore": False,
                    "totalResults": 1,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://gamma-api.polymarket.com",
        transport=transport,
        trust_env=False,
    ) as client:
        gamma = GammaClient(client=client)
        result = await gamma.search_public_profiles("market", limit_per_type=10, page=2)

    request = requests[0]
    assert request.url.params.get("q") == "market"
    assert request.url.params.get("limit_per_type") == "10"
    assert request.url.params.get("page") == "2"
    assert request.url.params.get("search_profiles") == "true"
    assert request.url.params.get("search_tags") == "false"
    assert len(result.profiles) == 1
    assert result.profiles[0].profile_id == "profile-1"
    assert result.profiles[0].profile_image_optimized == "https://example.com/profile-optimized.png"
    assert result.pagination is not None
    assert result.pagination.has_more is False
    assert result.pagination.total_results == 1
