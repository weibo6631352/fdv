from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class DomainEvent:
    name: str
    trace_id: str
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)

