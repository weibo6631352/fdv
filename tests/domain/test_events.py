from __future__ import annotations

from datetime import datetime, timezone

from fdv_trader.domain.events import AuditEvent, OutboxEvent, sanitize_raw_response
from fdv_trader.infra.outbox import OutboxEvent as InfraOutboxEvent
from fdv_trader.observability.audit import AuditEvent as ObservabilityAuditEvent


def test_canonical_event_classes_are_shared_across_modules() -> None:
    assert ObservabilityAuditEvent is AuditEvent
    assert InfraOutboxEvent is OutboxEvent


def test_audit_event_normalizes_utc_and_redacts_sensitive_fields() -> None:
    event = AuditEvent(
        event_type="order_submitted",
        trace_id="trace",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        updated_at=datetime(2026, 1, 1, 11, 59, 59),
        raw_response={
            "authorization": "Bearer abc123",
            "nested": {"api_key": "secret-value"},
        },
    )

    assert event.created_at.tzinfo == timezone.utc
    assert event.updated_at == event.created_at
    assert event.raw_response is not None
    assert "abc123" not in event.raw_response
    assert "secret-value" not in event.raw_response
    assert "[REDACTED]" in event.raw_response


def test_sanitize_raw_response_limits_and_redacts() -> None:
    summary = sanitize_raw_response({"api_key": "secret", "value": "ok"}, max_length=64)

    assert summary is not None
    assert "secret" not in summary
    assert "[REDACTED]" in summary
