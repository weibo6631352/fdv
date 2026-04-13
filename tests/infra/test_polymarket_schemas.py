from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polymarket_trader.infra.polymarket.schemas import (
    build_market_subscription_request,
    build_user_subscription_request,
    normalize_balance_allowance_payload,
    normalize_gamma_profile,
    parse_ws_message,
)


def test_normalize_balance_allowance_payload_reads_clob_fields() -> None:
    dto = normalize_balance_allowance_payload(
        {
            "data": {
                "balance": "100.25",
                "allowance": "90.5",
                "updated_at": "2026-01-01T12:00:00+00:00",
            }
        }
    )

    assert dto.balance_usdc == Decimal("100.25")
    assert dto.allowance_usdc == Decimal("90.5")
    assert dto.updated_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_build_market_subscription_request_uses_official_payload_shape() -> None:
    payload = build_market_subscription_request(("token-1", "token-2"))

    assert payload == {
        "assets_ids": ["token-1", "token-2"],
        "type": "market",
        "custom_feature_enabled": True,
    }


def test_build_user_subscription_request_and_parse_ws_message_follow_official_fields() -> None:
    payload = build_user_subscription_request(
        ("0x" + "1" * 64,),
        auth={
            "apiKey": "key",
            "secret": "secret",
            "passphrase": "passphrase",
        },
    )

    assert payload == {
        "auth": {
            "apiKey": "key",
            "secret": "secret",
            "passphrase": "passphrase",
        },
        "markets": ["0x" + "1" * 64],
        "type": "user",
    }

    message = parse_ws_message(
        {
            "event_type": "order",
            "type": "PLACEMENT",
            "asset_id": "token-1",
            "market": "0x" + "1" * 64,
        },
        channel_hint="user",
    )

    assert message.message_type == "order"
    assert message.token_id == "token-1"
    assert message.condition_id == "0x" + "1" * 64


def test_normalize_gamma_profile_maps_current_public_profile_fields() -> None:
    dto = normalize_gamma_profile(
        {
            "data": {
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
            }
        }
    )

    assert dto.created_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert dto.proxy_wallet == "0x1111111111111111111111111111111111111111"
    assert dto.profile_image == "https://example.com/avatar.png"
    assert dto.display_username_public is True
    assert dto.bio == "market watcher"
    assert dto.pseudonym == "market-watch-001"
    assert dto.name == "Market Watcher"
    assert dto.x_username == "marketwatcher"
    assert dto.verified_badge is True
    assert len(dto.users) == 1
    assert dto.users[0].user_id == "user-1"
    assert dto.users[0].creator is True
    assert dto.users[0].mod is False
