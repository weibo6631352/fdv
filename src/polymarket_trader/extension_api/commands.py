from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class FrameworkCommandAction(StrEnum):
    PAUSE_MARKET = "pause_market"
    RESUME_MARKET = "resume_market"
    PAUSE_ENTRIES = "pause_entries"
    TRIGGER_RECONCILE = "trigger_reconcile"
    REFRESH_MARKET = "refresh_market"
    EMIT_ALERT = "emit_alert"
    RECORD_AUDIT = "record_audit"
    SUBSCRIBE_MARKET = "subscribe_market"
    UNSUBSCRIBE_MARKET = "unsubscribe_market"


@dataclass(frozen=True, slots=True)
class ExtensionCommand:
    action: FrameworkCommandAction
    reason: str
    condition_id: str | None = None
    token_id: str | None = None
    market_slug: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def pause_market(cls, *, condition_id: str, reason: str) -> "ExtensionCommand":
        return cls(action=FrameworkCommandAction.PAUSE_MARKET, condition_id=condition_id, reason=reason)

    @classmethod
    def trigger_reconcile(
        cls,
        *,
        reason: str,
        condition_id: str | None = None,
    ) -> "ExtensionCommand":
        return cls(action=FrameworkCommandAction.TRIGGER_RECONCILE, condition_id=condition_id, reason=reason)
