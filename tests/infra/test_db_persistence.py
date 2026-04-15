from __future__ import annotations

from datetime import datetime, timezone

from polymarket_trader.infra.db.persistence import _audit_event_from_record


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
