from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polymarket_trader.infra.polymarket.schemas import (
    build_market_subscription_request,
    build_user_subscription_request,
    gamma_event_to_raw_market_events,
    normalize_balance_allowance_payload,
    normalize_gamma_market,
    parse_ws_messages,
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


def test_parse_ws_messages_flattens_array_frame_and_infers_book_type() -> None:
    messages = parse_ws_messages(
        [
            {
                "market": "condition-1",
                "asset_id": "token-1",
                "bids": [{"price": "0.55", "size": "10"}],
                "asks": [{"price": "0.43", "size": "12"}],
                "timestamp": "1757908892351",
            }
        ],
        channel_hint="market",
    )

    assert len(messages) == 1
    assert messages[0].message_type == "book"
    assert messages[0].token_id == "token-1"
    assert messages[0].condition_id == "condition-1"


def test_normalize_gamma_market_reads_clob_token_ids() -> None:
    dto = normalize_gamma_market(
        {
            "conditionId": "condition-1",
            "slug": "sample-market-a",
            "question": "Sample question?",
            "clobTokenIds": "[\"yes-1\",\"no-1\"]",
            "orderPriceMinTickSize": "0.01",
            "orderMinSize": "1",
        }
    )

    assert dto.yes_token_id == "yes-1"
    assert dto.no_token_id == "no-1"
    assert dto.to_market().no_token_id == "no-1"


def test_gamma_event_to_raw_market_events_inherits_parent_event_context() -> None:
    raw_events = gamma_event_to_raw_market_events(
        {
            "id": "event-1",
            "slug": "sample-event",
            "title": "Sample Threshold Event",
            "tags": [
                {
                    "label": "Crypto",
                    "slug": "crypto",
                }
            ],
            "markets": [
                {
                    "conditionId": "condition-1",
                    "slug": "sample-market-a",
                    "question": "Sample question?",
                    "clobTokenIds": "[\"yes-1\",\"no-1\"]",
                    "orderPriceMinTickSize": "0.01",
                    "orderMinSize": "1",
                }
            ],
        },
        source="gamma",
        trace_id="trace-1",
    )

    assert len(raw_events) == 1
    assert raw_events[0].payload["eventTitle"] == "Sample Threshold Event"
    assert raw_events[0].payload["eventSlug"] == "sample-event"
    assert raw_events[0].payload["eventId"] == "event-1"
    assert raw_events[0].payload["tags"] == [{"label": "Crypto", "slug": "crypto"}]
