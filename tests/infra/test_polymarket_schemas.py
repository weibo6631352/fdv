from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fdv_trader.infra.polymarket.schemas import (
    build_market_subscription_request,
    build_user_subscription_request,
    normalize_balance_allowance_payload,
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
