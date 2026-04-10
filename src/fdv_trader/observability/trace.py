from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def new_trace_id() -> str:
    trace_id = uuid4().hex
    trace_id_var.set(trace_id)
    return trace_id


def current_trace_id() -> str | None:
    return trace_id_var.get()

