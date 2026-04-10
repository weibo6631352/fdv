from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    trace_id: str
    created_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)

