from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polymarket_trader.domain.market import TradingStatus
from polymarket_trader.infra.db.models import MarketModel
from polymarket_trader.infra.db.persistence import _audit_event_from_record, _market_from_record
from tests.helpers.markets import build_binary_market


def test_audit_event_from_record_restores_serialized_timestamps() -> None:
    event = _audit_event_from_record(
        {
            "trace_id": "trace-1",
            "event_title": "market_filtered_out",
            "created_at": "2026-04-15T07:39:39.514588+00:00",
            "updated_at": "2026-04-15T07:39:39.600000+00:00",
        }
    )

    assert event is not None
    assert event.created_at == datetime(2026, 4, 15, 7, 39, 39, 514588, tzinfo=timezone.utc)
    assert event.updated_at == datetime(2026, 4, 15, 7, 39, 39, 600000, tzinfo=timezone.utc)
    assert event.payload["created_at"] == "2026-04-15 07:39:39.514588+00:00"
    assert event.payload["updated_at"] == "2026-04-15 07:39:39.600000+00:00"


def test_market_from_record_prefers_fee_schedule_rate_from_raw_payload() -> None:
    market = _market_from_record(
        {
            "condition_id": "condition-1",
            "market_slug": "sample-market-a",
            "token_ids": ["yes-token", "no-token"],
            "outcomes": [
                {"token_id": "yes-token", "outcome": "YES"},
                {"token_id": "no-token", "outcome": "NO"},
            ],
            "tick_size": "0.01",
            "min_order_size": "1",
            "taker_base_fee_bps": 1000,
            "fee_rate_bps": 1000,
            "raw_payload": {
                "feeSchedule": {
                    "rate": "0.072",
                }
            },
        }
    )

    assert market is not None
    assert market.taker_base_fee_bps == 72
    assert market.fee_rate_bps == 72


def test_market_model_to_domain_prefers_fee_schedule_rate_from_raw_payload() -> None:
    model = MarketModel.from_domain(
        build_binary_market(
            condition_id="condition-1",
            market_slug="sample-market-a",
            no_token_id="no-token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            taker_base_fee_bps=1000,
            fee_rate_bps=1000,
            trading_status=TradingStatus.ELIGIBLE,
        ),
        trace_id="trace-1",
        source="test",
        raw_payload={
            "feeSchedule": {
                "rate": "0.072",
            }
        },
    )

    market = model.to_domain()

    assert market.taker_base_fee_bps == 72
    assert market.fee_rate_bps == 72
