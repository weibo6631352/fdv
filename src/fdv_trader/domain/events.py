from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping


class DomainEventType(StrEnum):
    MARKET_DISCOVERED = "market_discovered"
    MARKET_FILTERED_IN = "market_filtered_in"
    MARKET_FILTERED_OUT = "market_filtered_out"
    ORDERBOOK = "orderbook"
    ENTRY_SIGNAL_TRIGGERED = "entry_signal_triggered"
    RISK_CHECK_PASSED = "risk_check_passed"
    RISK_CHECK_FAILED = "risk_check_failed"
    ORDER_CREATED = "order_created"
    ORDER_SIGNED = "order_signed"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_MATCHED = "order_matched"
    ORDER_NO_FILL = "order_no_fill"
    ORDER_PARTIALLY_FILLED = "order_partially_filled"
    EXIT_ORDER_SUBMITTED = "exit_order_submitted"
    ORDER_CANCEL_REQUESTED = "order_cancel_requested"
    ORDER_CANCELLED = "order_cancelled"
    REPLACE_ORDER_SUBMITTED = "replace_order_submitted"
    TRADE_MINED = "trade_mined"
    TRADE_CONFIRMED = "trade_confirmed"
    RETRY = "retry"
    SKIPPED = "skipped"
    ERROR = "error"


class OutboxPriority(StrEnum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


def _utc_now() -> datetime:
    return datetime.utcnow()


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    # 这里保留的是域内稳定字段；外部 SDK / DB / HTTP 的原始字段放到 payload/raw_response，
    # 避免协议字段变化直接扩散到 domain。
    trace_id: str
    event_type: DomainEventType | str
    event_id: str
    market_slug: str | None = None
    condition_id: str | None = None
    token_id: str | None = None
    reason: str = ""
    created_at: datetime = field(default_factory=_utc_now)

    @property
    def name(self) -> str:
        return str(self.event_type)

    @property
    def occurred_at(self) -> datetime:
        return self.created_at


@dataclass(frozen=True, slots=True)
class DomainEvent(EventEnvelope):
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fill:
    trace_id: str
    event_type: DomainEventType | str = DomainEventType.TRADE_CONFIRMED
    event_id: str = ""
    market_slug: str | None = None
    condition_id: str | None = None
    token_id: str | None = None
    reason: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    order_id: str | None = None
    trade_id: str | None = None
    side: str | None = None
    price: Decimal | None = None
    size: Decimal | None = None
    notional_usdc: Decimal | None = None
    status: str = "confirmed"
    confirmed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuditEvent(EventEnvelope):
    event_title: str | None = None
    outcome: str | None = None
    side: str | None = None
    order_type: str | None = None
    price: Decimal | None = None
    size: Decimal | None = None
    notional_usdc: Decimal | None = None
    order_id: str | None = None
    trade_id: str | None = None
    tx_hash: str | None = None
    status: str | None = None
    raw_response: Mapping[str, Any] | str | None = None
    updated_at: datetime | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OutboxEvent(EventEnvelope):
    payload: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    retry_count: int = 0
    last_error: str | None = None
    priority: OutboxPriority = OutboxPriority.P0
    raw_response_summary: str | None = None
