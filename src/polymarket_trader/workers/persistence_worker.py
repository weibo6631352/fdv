from __future__ import annotations


import asyncio
import inspect
import logging
from collections import Counter, deque
from contextlib import suppress
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from polymarket_trader.domain.events import AuditEvent, DomainEventType, OutboxEvent

logger = logging.getLogger(__name__)

_MARKET_EVENT_TYPES = {
    DomainEventType.MARKET_DISCOVERED.value,
    DomainEventType.MARKET_UPDATED.value,
    DomainEventType.MARKET_FILTERED_IN.value,
    DomainEventType.MARKET_FILTERED_OUT.value,
    DomainEventType.MARKET_RESOLVED_OR_DISABLED.value,
}
_ACCOUNT_EVENT_TYPES = {
    DomainEventType.BALANCE_UPDATED.value,
}
_ORDERBOOK_EVENT_TYPES = {
    DomainEventType.ORDERBOOK.value,
    DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
    DomainEventType.ENTRY_PRICE_TOUCHED.value,
}
_ORDER_EVENT_TYPES = {
    DomainEventType.ORDER_CREATED.value,
    DomainEventType.ORDER_SIGNED.value,
    DomainEventType.ORDER_SUBMITTED.value,
    DomainEventType.ORDER_REJECTED.value,
    DomainEventType.ORDER_MATCHED.value,
    DomainEventType.ORDER_NO_FILL.value,
    DomainEventType.ORDER_PARTIALLY_FILLED.value,
    DomainEventType.ORDER_STATE_UPDATED.value,
    DomainEventType.ORDER_CANCEL_REQUESTED.value,
    DomainEventType.ORDER_CANCELLED.value,
    DomainEventType.REPLACE_ORDER_SUBMITTED.value,
    DomainEventType.RESTING_BUY_DETECTED.value,
}
_FILL_EVENT_TYPES = {
    DomainEventType.FILL_RECORDED.value,
    DomainEventType.TRADE_MINED.value,
    DomainEventType.TRADE_CONFIRMED.value,
}
_POSITION_EVENT_TYPES = {
    DomainEventType.POSITION_UPDATED.value,
}
_ALLOCATION_EVENT_TYPES = {
    DomainEventType.SKIPPED.value,
    DomainEventType.RISK_CHECK_PASSED.value,
    DomainEventType.RISK_CHECK_FAILED.value,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(item) for item in value]
    return str(value)


def _text(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping(payload: Mapping[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return None


def _mapping_list(payload: Mapping[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return [dict(value)]
        if isinstance(value, list):
            records: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, Mapping):
                    records.append(dict(item))
            if records:
                return records
    return []


def _base_meta(event: OutboxEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "event_type": str(event.event_type),
        "source_event_type": str(event.event_type),
        "source_event_id": event.event_id,
        "market_slug": event.market_slug,
        "condition_id": event.condition_id,
        "token_id": event.token_id,
        "reason": event.reason,
        "created_at": _to_jsonable(event.created_at),
        "priority": event.priority,
        "retry_count": event.retry_count,
        "last_error": event.last_error,
        "idempotency_key": event.idempotency_key,
        "raw_payload": _to_jsonable(payload),
    }


def _kind_idempotency_key(kind: str, event: OutboxEvent) -> str:
    return f"{kind}:{event.idempotency_key}"


def _event_type_text(event: OutboxEvent) -> str:
    return str(event.event_type).strip()


def _route_key(event: OutboxEvent) -> str:
    if event.merge_key:
        return event.merge_key
    parts = [
        str(event.event_type),
        event.market_slug or "",
        event.condition_id or "",
        event.token_id or "",
    ]
    return "|".join(parts)


def _safe_first_payload_value(payload: Mapping[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


@runtime_checkable
class PersistenceOutbox(Protocol):
    async def get(self) -> OutboxEvent: ...

    async def ack(self, event: str | OutboxEvent) -> None: ...

    async def retry(self, event: str | OutboxEvent, *, last_error: str | None = None) -> OutboxEvent: ...

    async def dead_letter(self, event: str | OutboxEvent, *, last_error: str | None = None) -> OutboxEvent: ...


@runtime_checkable
class PersistenceRepository(Protocol):
    async def save_audit_event(self, record: Mapping[str, Any]) -> Any: ...

    async def save_audit_events(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_market_snapshot(self, record: Mapping[str, Any]) -> Any: ...

    async def save_market_snapshots(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_orderbook_snapshot(self, record: Mapping[str, Any]) -> Any: ...

    async def save_orderbook_snapshots(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_order(self, record: Mapping[str, Any]) -> Any: ...

    async def save_orders(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_fill(self, record: Mapping[str, Any]) -> Any: ...

    async def save_fills(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_position(self, record: Mapping[str, Any]) -> Any: ...

    async def save_positions(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_allocation(self, record: Mapping[str, Any]) -> Any: ...

    async def save_allocations(self, records: Sequence[Mapping[str, Any]]) -> Any: ...

    async def save_outbox_event(self, record: Mapping[str, Any]) -> Any: ...

    async def save_outbox_events(self, records: Sequence[Mapping[str, Any]]) -> Any: ...


@dataclass(frozen=True, slots=True)
class PersistenceWorkerResult:
    batch_size: int
    merged_events: int
    written_records: int
    failed_events: int
    retried_events: int
    dead_lettered_events: int
    last_event_lag_ms: int
    average_event_lag_ms: int
    route_write_counts: tuple[tuple[str, int], ...]
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class PersistenceWorkerSnapshot:
    processed_events: int
    persisted_events: int
    retried_events: int
    dead_lettered_events: int
    merged_events: int
    written_records: int
    failed_records: int
    last_batch_size: int
    last_event_lag_ms: int
    average_event_lag_ms: int
    max_event_lag_ms: int
    outbox_depth: int
    outbox_retained_depth: int
    outbox_dead_letter_depth: int
    last_error: str | None
    last_persisted_at: datetime | None
    last_processed_at: datetime | None
    route_write_counts: tuple[tuple[str, int], ...]
    last_result: PersistenceWorkerResult | None
    recent_results: tuple[PersistenceWorkerResult, ...]


@dataclass(slots=True)
class _WorkerStats:
    processed_events: int = 0
    persisted_events: int = 0
    retried_events: int = 0
    dead_lettered_events: int = 0
    merged_events: int = 0
    written_records: int = 0
    failed_records: int = 0
    last_batch_size: int = 0
    last_event_lag_ms: int = 0
    max_event_lag_ms: int = 0
    lag_total_ms: int = 0
    lag_samples: int = 0
    last_error: str | None = None
    last_persisted_at: datetime | None = None
    last_processed_at: datetime | None = None
    route_write_counts: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class _PlannedRecord:
    event: OutboxEvent
    kind: str
    record: Mapping[str, Any]


class PersistenceWorker:
    """P3 异步落库 worker。

    这里的责任只有一件事：把 outbox 里的交易事件尽快、尽量可靠地写到仓储层。
    数据库失败不能反向阻塞交易热路径，所以 worker 只消费 outbox，不参与 P0 决策。
    """

    priority = "P3"

    def __init__(
        self,
        *,
        outbox: PersistenceOutbox | None = None,
        repository: PersistenceRepository | None = None,
        batch_size: int = 64,
        poll_timeout_s: float = 1.0,
        drain_timeout_s: float = 0.05,
        max_retry_count: int = 3,
        low_priority_merge_window_s: float = 0.05,
    ) -> None:
        self._outbox = outbox
        self._repository = repository
        self._batch_size = max(1, batch_size)
        self._poll_timeout_s = max(0.01, poll_timeout_s)
        self._drain_timeout_s = max(0.0, drain_timeout_s)
        self._max_retry_count = max(0, max_retry_count)
        self._low_priority_merge_window_s = max(0.0, low_priority_merge_window_s)
        self._stop_event = asyncio.Event()
        self._stats = _WorkerStats()
        self._recent_results: deque[PersistenceWorkerResult] = deque(maxlen=8)

    async def run(self) -> None:
        if self._outbox is None or self._repository is None:
            raise RuntimeError("PersistenceWorker requires both outbox and repository to run")

        while not self._stop_event.is_set():
            try:
                result = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # P3 失败要记录和退避，但不能把交易链路一起拖停。
                logger.exception("persistence worker loop failed")
                await asyncio.sleep(self._drain_timeout_s or 0.05)
                continue
            if result is None:
                continue

    def stop(self) -> None:
        self._stop_event.set()

    async def run_once(self) -> PersistenceWorkerResult | None:
        if self._outbox is None or self._repository is None:
            raise RuntimeError("PersistenceWorker requires both outbox and repository to run")

        event = await self._poll_event()
        if event is None:
            return None

        batch = [event]
        batch.extend(await self._drain_batch())
        coalesced_batch, merged_events = self._coalesce_low_priority(batch)
        result = await self._persist_batch(coalesced_batch, merged_events=merged_events)
        self._recent_results.append(result)
        return result

    def snapshot(self) -> PersistenceWorkerSnapshot:
        outbox_depth, retained_depth, dead_letter_depth = self._outbox_depths()
        average_event_lag_ms = (
            int(self._stats.lag_total_ms / self._stats.lag_samples)
            if self._stats.lag_samples > 0
            else 0
        )
        return PersistenceWorkerSnapshot(
            processed_events=self._stats.processed_events,
            persisted_events=self._stats.persisted_events,
            retried_events=self._stats.retried_events,
            dead_lettered_events=self._stats.dead_lettered_events,
            merged_events=self._stats.merged_events,
            written_records=self._stats.written_records,
            failed_records=self._stats.failed_records,
            last_batch_size=self._stats.last_batch_size,
            last_event_lag_ms=self._stats.last_event_lag_ms,
            average_event_lag_ms=average_event_lag_ms,
            max_event_lag_ms=self._stats.max_event_lag_ms,
            outbox_depth=outbox_depth,
            outbox_retained_depth=retained_depth,
            outbox_dead_letter_depth=dead_letter_depth,
            last_error=self._stats.last_error,
            last_persisted_at=self._stats.last_persisted_at,
            last_processed_at=self._stats.last_processed_at,
            route_write_counts=tuple(sorted(self._stats.route_write_counts.items())),
            last_result=self._recent_results[-1] if self._recent_results else None,
            recent_results=tuple(self._recent_results),
        )

    async def _poll_event(self) -> OutboxEvent | None:
        if self._outbox is None:
            return None
        try:
            return await asyncio.wait_for(self._outbox.get(), timeout=self._poll_timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            return None

    async def _drain_batch(self) -> list[OutboxEvent]:
        if self._outbox is None:
            return []
        events: list[OutboxEvent] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(self._drain_timeout_s, self._low_priority_merge_window_s)
        while len(events) + 1 < self._batch_size:
            timeout = deadline - loop.time()
            if timeout <= 0:
                break
            try:
                event = await asyncio.wait_for(self._outbox.get(), timeout=timeout)
            except (asyncio.TimeoutError, TimeoutError):
                break
            events.append(event)
        return events

    def _coalesce_low_priority(
        self,
        events: Sequence[OutboxEvent],
    ) -> tuple[tuple[OutboxEvent, ...], int]:
        # 低优先级快照可以合并、降采样，P0 / P1 事件则严格保留。
        merged_events = 0
        critical: list[OutboxEvent] = []
        latest_by_key: dict[str, OutboxEvent] = {}
        order: list[str] = []

        for event in events:
            if event.is_critical:
                critical.append(event)
                continue
            key = _route_key(event)
            previous = latest_by_key.get(key)
            if previous is not None:
                merged_events += 1
            else:
                order.append(key)
            latest_by_key[key] = event

        low_priority = [latest_by_key[key] for key in order]
        low_priority.sort(key=lambda item: (item.created_at, item.event_id))
        return tuple(critical + low_priority), merged_events

    async def _persist_batch(
        self,
        events: Sequence[OutboxEvent],
        *,
        merged_events: int,
    ) -> PersistenceWorkerResult:
        if self._repository is None or self._outbox is None:
            raise RuntimeError("PersistenceWorker requires both outbox and repository to run")

        self._stats.last_batch_size = len(events)
        self._stats.merged_events += merged_events
        self._stats.processed_events += len(events)
        self._stats.last_processed_at = _utc_now()

        planned_records, required_record_counts = self._build_planned_records(events)
        if not planned_records:
            return self._finalize_batch(
                events=events,
                required_record_counts=required_record_counts,
                merged_events=merged_events,
            )

        success_record_counts: Counter[str] = Counter()
        failed_events: dict[str, str] = {}
        route_write_counts: Counter[str] = Counter()
        route_order = ("audit", "market", "orderbook", "order", "fill", "position", "allocation", "outbox")

        for kind in route_order:
            kind_items = [item for item in planned_records if item.kind == kind]
            if not kind_items:
                continue
            success, failures, written_count = await self._write_kind(kind, kind_items)
            for event_id, record_count in success.items():
                success_record_counts[event_id] += record_count
            for event_id, message in failures.items():
                failed_events.setdefault(event_id, message)
            route_write_counts[kind] += written_count

        return await self._finalize_event_outcomes(
            events=events,
            required_record_counts=required_record_counts,
            success_record_counts=success_record_counts,
            failed_events=failed_events,
            route_write_counts=route_write_counts,
            merged_events=merged_events,
        )

    async def _write_kind(
        self,
        kind: str,
        items: Sequence[_PlannedRecord],
    ) -> tuple[dict[str, int], dict[str, str], int]:
        if self._repository is None:
            raise RuntimeError("PersistenceWorker requires a repository")

        batch_method = self._select_repository_method(kind, batch=True)
        single_method = self._select_repository_method(kind, batch=False)

        if batch_method is not None and len(items) > 1:
            records = [item.record for item in items]
            try:
                await self._invoke_repository_method(batch_method, records)
                return self._success_map(items), {}, len(items)
            except Exception as exc:
                logger.warning(
                    "persistence batch write failed for %s, falling back to single writes: %s",
                    kind,
                    exc,
                )

        success: dict[str, int] = {}
        failures: dict[str, str] = {}
        written_count = 0

        for item in items:
            if single_method is not None:
                method_name = single_method
                argument: Any = item.record
            elif batch_method is not None:
                method_name = batch_method
                argument = [item.record]
            else:
                failures[item.event.event_id] = f"missing repository method for kind={kind}"
                continue
            try:
                await self._invoke_repository_method(method_name, argument)
            except Exception as exc:
                failures.setdefault(item.event.event_id, self._format_error(kind, exc))
            else:
                success[item.event.event_id] = success.get(item.event.event_id, 0) + 1
                written_count += 1

        return success, failures, written_count

    async def _finalize_event_outcomes(
        self,
        *,
        events: Sequence[OutboxEvent],
        required_record_counts: Mapping[str, int],
        success_record_counts: Mapping[str, int],
        failed_events: Mapping[str, str],
        route_write_counts: Mapping[str, int],
        merged_events: int,
    ) -> PersistenceWorkerResult:
        persisted_events = 0
        retried_events = 0
        dead_lettered_events = 0
        failed_records = 0

        for event in events:
            required = required_record_counts.get(event.event_id, 0)
            succeeded = success_record_counts.get(event.event_id, 0)
            if required > 0 and succeeded >= required and event.event_id not in failed_events:
                await self._ack(event)
                persisted_events += 1
                continue

            failed_reason = failed_events.get(event.event_id, "persistence write incomplete")
            failed_records += max(required - succeeded, 0)
            retried_or_dead = await self._retry_or_dead_letter(event, failed_reason)
            if retried_or_dead == "retry":
                retried_events += 1
            else:
                dead_lettered_events += 1

        written_records = sum(success_record_counts.values())
        self._stats.persisted_events += persisted_events
        self._stats.retried_events += retried_events
        self._stats.dead_lettered_events += dead_lettered_events
        self._stats.written_records += written_records
        self._stats.failed_records += failed_records
        self._stats.route_write_counts.update(route_write_counts)

        last_event_lag_ms = 0
        if events:
            lag_values = [self._lag_ms(event) for event in events]
            last_event_lag_ms = lag_values[-1]
            self._stats.last_event_lag_ms = last_event_lag_ms
            self._stats.max_event_lag_ms = max(self._stats.max_event_lag_ms, max(lag_values))
            self._stats.lag_total_ms += sum(lag_values)
            self._stats.lag_samples += len(lag_values)

        if failed_events:
            self._stats.last_error = next(iter(failed_events.values()))
        elif events:
            self._stats.last_error = None

        return PersistenceWorkerResult(
            batch_size=len(events),
            merged_events=merged_events,
            written_records=written_records,
            failed_events=len(failed_events),
            retried_events=retried_events,
            dead_lettered_events=dead_lettered_events,
            last_event_lag_ms=last_event_lag_ms,
            average_event_lag_ms=(
                int(self._stats.lag_total_ms / self._stats.lag_samples)
                if self._stats.lag_samples > 0
                else 0
            ),
            route_write_counts=tuple(sorted(route_write_counts.items())),
        )

    async def _finalize_batch(
        self,
        *,
        events: Sequence[OutboxEvent],
        required_record_counts: Mapping[str, int],
        merged_events: int,
    ) -> PersistenceWorkerResult:
        return await self._finalize_event_outcomes(
            events=events,
            required_record_counts=required_record_counts,
            success_record_counts={},
            failed_events={},
            route_write_counts={},
            merged_events=merged_events,
        )

    async def _retry_or_dead_letter(self, event: OutboxEvent, reason: str) -> str:
        if self._outbox is None:
            raise RuntimeError("PersistenceWorker requires an outbox")
        if _is_retryable_error(reason) and event.retry_count < self._max_retry_count:
            await self._outbox.retry(event, last_error=reason)
            return "retry"
        await self._outbox.dead_letter(event, last_error=reason)
        return "dead_letter"

    async def _ack(self, event: OutboxEvent) -> None:
        if self._outbox is None:
            raise RuntimeError("PersistenceWorker requires an outbox")
        await self._outbox.ack(event)

    def _build_planned_records(
        self,
        events: Sequence[OutboxEvent],
    ) -> tuple[list[_PlannedRecord], dict[str, int]]:
        planned_records: list[_PlannedRecord] = []
        required_record_counts: dict[str, int] = {}

        for event in events:
            event_records = self._route_event(event)
            required_record_counts[event.event_id] = len(event_records)
            for kind, record in event_records:
                planned_records.append(_PlannedRecord(event=event, kind=kind, record=record))

        return planned_records, required_record_counts

    def _route_event(self, event: OutboxEvent) -> list[tuple[str, Mapping[str, Any]]]:
        records: list[tuple[str, Mapping[str, Any]]] = []
        event_type = _event_type_text(event)
        payload = dict(event.payload)

        records.append(("audit", self._build_audit_record(event, payload)))

        special_allocation_records = self._build_allocation_records(event, payload)
        for record in special_allocation_records:
            records.append(("allocation", record))

        if event_type in _MARKET_EVENT_TYPES:
            records.append(("market", self._build_market_record(event, payload)))

        if event_type in _ACCOUNT_EVENT_TYPES:
            records.append(("account", self._build_account_record(event, payload)))

        if event_type in _ORDERBOOK_EVENT_TYPES:
            records.append(("orderbook", self._build_orderbook_record(event, payload)))

        if event_type in _ORDER_EVENT_TYPES:
            records.append(("order", self._build_order_record(event, payload)))

        if event_type in _FILL_EVENT_TYPES:
            records.extend(("fill", record) for record in self._build_fill_records(event, payload))

        if event_type in _POSITION_EVENT_TYPES:
            records.extend(("position", record) for record in self._build_position_records(event, payload))

        records.append(("outbox", self._build_outbox_record(event, payload)))
        return records

    def _build_audit_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        audit = AuditEvent(
            event_title=str(event.event_type),
            trace_id=event.trace_id,
            event_id=event.event_id,
            market_slug=event.market_slug,
            condition_id=event.condition_id,
            token_id=event.token_id,
            reason=event.reason or "",
            created_at=event.created_at,
            raw_response=event.raw_response_summary,
            payload={
                "source_event_id": event.event_id,
                "source_event_type": str(event.event_type),
                "source_payload": _to_jsonable(payload),
                "idempotency_key": event.idempotency_key,
                "priority": event.priority,
                "retry_count": event.retry_count,
            },
        )
        record = audit.to_payload()
        record["idempotency_key"] = _kind_idempotency_key("audit", event)
        record["source_event_id"] = event.event_id
        record["source_event_type"] = str(event.event_type)
        record["source_payload"] = _to_jsonable(payload)
        return _to_jsonable(record)

    def _build_market_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        market = _mapping(payload, "market", "market_snapshot")
        fees = _mapping(market or {}, "fees") or {}
        if market is None:
            fees = {
                "enabled": _safe_first_payload_value(payload, "fees_enabled"),
                "maker_base_fee_bps": _safe_first_payload_value(payload, "maker_base_fee_bps"),
                "taker_base_fee_bps": _safe_first_payload_value(payload, "taker_base_fee_bps"),
                "fee_rate_bps": _safe_first_payload_value(payload, "fee_rate_bps"),
                "fee_rate_updated_at": _safe_first_payload_value(payload, "fee_rate_updated_at"),
            }
            market = {
                "condition_id": event.condition_id,
                "market_slug": event.market_slug,
                "event_id": _safe_first_payload_value(payload, "event_id", "source_event_id"),
                "event_title": _safe_first_payload_value(payload, "event_title", "title"),
                "event_slug": _safe_first_payload_value(payload, "event_slug", "slug"),
                "yes_token_id": _safe_first_payload_value(payload, "yes_token_id"),
                "no_token_id": _safe_first_payload_value(payload, "no_token_id"),
                "tick_size": _safe_first_payload_value(payload, "tick_size"),
                "min_order_size": _safe_first_payload_value(payload, "min_order_size"),
                "neg_risk": _safe_first_payload_value(payload, "neg_risk"),
                "fees": fees,
                "category": _safe_first_payload_value(payload, "category"),
                "tags": _safe_first_payload_value(payload, "tags"),
                "matched_keywords": _safe_first_payload_value(payload, "matched_keywords"),
                "trading_status": "rejected"
                if _safe_first_payload_value(payload, "accepted") is False
                else _safe_first_payload_value(payload, "trading_status"),
                "reject_reason": _safe_first_payload_value(
                    payload,
                    "reject_reason",
                    "classification_reason",
                ),
            }

        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("market", event),
                "source": _safe_first_payload_value(payload, "source"),
                "discovery_kind": _safe_first_payload_value(payload, "discovery_kind"),
                "classification_status": _safe_first_payload_value(payload, "classification_status"),
                "classification_reason": _safe_first_payload_value(
                    payload,
                    "classification_reason",
                    "reject_reason",
                ),
                "classification_detail": _safe_first_payload_value(payload, "classification_detail"),
                "matched_fields": _to_jsonable(_safe_first_payload_value(payload, "matched_fields")),
                "matched_keywords": _to_jsonable(_safe_first_payload_value(payload, "matched_keywords")),
                "accepted": _safe_first_payload_value(payload, "accepted"),
                "fees_enabled": _safe_first_payload_value(fees, "enabled"),
                "maker_base_fee_bps": _safe_first_payload_value(fees, "maker_base_fee_bps"),
                "taker_base_fee_bps": _safe_first_payload_value(fees, "taker_base_fee_bps"),
                "fee_rate_bps": _safe_first_payload_value(fees, "fee_rate_bps"),
                "fee_rate_updated_at": _safe_first_payload_value(fees, "fee_rate_updated_at"),
                "market_data": _to_jsonable(market),
            }
        )
        record.update(_to_jsonable(market))
        return record

    def _build_account_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = _base_meta(event)
        account = {
            "account_key": "primary",
            "balance_usdc": _safe_first_payload_value(payload, "balance_usdc"),
            "allowance_usdc": _safe_first_payload_value(payload, "allowance_usdc"),
            "user_ws_connected": _safe_first_payload_value(payload, "user_ws_connected"),
            "allow_new_buys": _safe_first_payload_value(payload, "allow_new_buys"),
            "paused_markets": _safe_first_payload_value(payload, "paused_markets"),
            "pause_reasons": _safe_first_payload_value(payload, "pause_reasons"),
            "last_reconcile_at": _safe_first_payload_value(payload, "last_reconcile_at"),
        }
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("account", event),
                "account_data": _to_jsonable(account),
            }
        )
        record.update(_to_jsonable(account))
        return record

    def _build_orderbook_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = _mapping(payload, "snapshot", "orderbook", "book")
        if snapshot is None:
            snapshot = {
                "token_id": event.token_id,
                "market_slug": event.market_slug,
                "condition_id": event.condition_id,
                "best_bid": _safe_first_payload_value(payload, "best_bid"),
                "best_ask": _safe_first_payload_value(payload, "best_ask"),
                "best_bid_size": _safe_first_payload_value(payload, "best_bid_size"),
                "best_ask_size": _safe_first_payload_value(payload, "best_ask_size"),
                "last_trade_price": _safe_first_payload_value(payload, "last_trade_price"),
                "tick_size": _safe_first_payload_value(payload, "tick_size"),
                "spread": _safe_first_payload_value(payload, "spread"),
                "buyable_no_depth": _safe_first_payload_value(payload, "buyable_no_depth"),
                "snapshot_time": _safe_first_payload_value(payload, "snapshot_time"),
                "needs_rest_snapshot": _safe_first_payload_value(payload, "needs_rest_snapshot"),
            }

        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("orderbook", event),
                "source": _safe_first_payload_value(payload, "source"),
                "snapshot_time": _safe_first_payload_value(payload, "snapshot_time"),
                "needs_rest_snapshot": _safe_first_payload_value(payload, "needs_rest_snapshot"),
                "spread": _safe_first_payload_value(payload, "spread"),
                "buyable_no_depth": _safe_first_payload_value(payload, "buyable_no_depth"),
                "orderbook_data": _to_jsonable(snapshot),
            }
        )
        record.update(_to_jsonable(snapshot))
        return record

    def _build_order_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        order = _mapping(payload, "order")
        if order is None:
            order = {
                "order_id": _safe_first_payload_value(payload, "order_id"),
                "trade_id": _safe_first_payload_value(payload, "trade_id"),
                "side": _safe_first_payload_value(payload, "side"),
                "order_type": _safe_first_payload_value(payload, "order_type"),
                "price": _safe_first_payload_value(payload, "price"),
                "amount_usdc": _safe_first_payload_value(payload, "amount_usdc"),
                "size_shares": _safe_first_payload_value(payload, "size_shares"),
                "filled_shares": _safe_first_payload_value(payload, "filled_shares"),
                "remaining_shares": _safe_first_payload_value(payload, "remaining_shares"),
                "notional_usdc": _safe_first_payload_value(payload, "notional_usdc"),
                "status": _safe_first_payload_value(payload, "status"),
                "reason": _safe_first_payload_value(payload, "reason"),
                "post_only": _safe_first_payload_value(payload, "post_only"),
            }

        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("order", event),
                "order_data": _to_jsonable(order),
            }
        )
        record.update(_to_jsonable(order))
        return record

    def _build_fill_records(
        self,
        event: OutboxEvent,
        payload: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        fills = _mapping_list(payload, "fill", "fills")
        if not fills:
            fills = [
                {
                    "event_id": event.event_id,
                    "trade_id": _safe_first_payload_value(payload, "trade_id"),
                    "order_id": _safe_first_payload_value(payload, "order_id"),
                    "side": _safe_first_payload_value(payload, "side"),
                    "price": _safe_first_payload_value(payload, "price"),
                    "size": _safe_first_payload_value(payload, "size"),
                    "notional_usdc": _safe_first_payload_value(payload, "notional_usdc"),
                    "status": _safe_first_payload_value(payload, "status"),
                    "confirmed_at": _safe_first_payload_value(payload, "confirmed_at"),
                }
            ]

        records: list[dict[str, Any]] = []
        for index, fill in enumerate(fills):
            record = _base_meta(event)
            record.update(
                {
                    "event_id": fill.get("event_id") or event.event_id,
                    "idempotency_key": _kind_idempotency_key("fill", event),
                    "fill_index": index,
                    "fill_data": _to_jsonable(fill),
                }
            )
            record.update(_to_jsonable(fill))
            records.append(record)
        return records

    def _build_position_records(
        self,
        event: OutboxEvent,
        payload: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        positions = _mapping_list(payload, "position", "positions")
        if not positions:
            positions = [
                {
                    "condition_id": event.condition_id,
                    "token_id": event.token_id,
                    "market_slug": event.market_slug,
                    "shares": _safe_first_payload_value(payload, "shares"),
                    "cost_usdc": _safe_first_payload_value(payload, "cost_usdc"),
                    "open_buy_shares": _safe_first_payload_value(payload, "open_buy_shares"),
                    "open_sell_shares": _safe_first_payload_value(payload, "open_sell_shares"),
                    "pending_buy_shares": _safe_first_payload_value(payload, "pending_buy_shares"),
                    "confirmed_shares": _safe_first_payload_value(payload, "confirmed_shares"),
                    "last_order_id": _safe_first_payload_value(payload, "last_order_id"),
                    "last_trade_id": _safe_first_payload_value(payload, "last_trade_id"),
                    "confirmation_status": _safe_first_payload_value(payload, "confirmation_status"),
                }
            ]

        records: list[dict[str, Any]] = []
        for index, position in enumerate(positions):
            record = _base_meta(event)
            record.update(
                {
                    "idempotency_key": _kind_idempotency_key("position", event),
                    "position_index": index,
                    "position_data": _to_jsonable(position),
                }
            )
            record.update(_to_jsonable(position))
            records.append(record)
        return records

    def _build_allocation_records(
        self,
        event: OutboxEvent,
        payload: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        allocation = _mapping(payload, "allocation")
        allocations = _mapping_list(payload, "allocations")
        plan = _mapping(payload, "allocation_plan")

        if allocation is None and allocations:
            records_source = allocations
        elif allocation is not None:
            records_source = [allocation]
        elif plan is not None and isinstance(plan.get("allocations"), list):
            records_source = [item for item in plan["allocations"] if isinstance(item, Mapping)]
        else:
            return []

        records: list[dict[str, Any]] = []
        plan_meta = _to_jsonable(plan) if plan is not None else None
        for index, allocation_item in enumerate(records_source):
            record = _base_meta(event)
            record.update(
                {
                    "idempotency_key": _kind_idempotency_key("allocation", event),
                    "allocation_index": index,
                    "allocation_plan": plan_meta,
                    "allocation_data": _to_jsonable(allocation_item),
                }
            )
            record.update(_to_jsonable(allocation_item))
            records.append(record)
        return records

    def _build_outbox_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": event.idempotency_key,
                "outbox_payload": _to_jsonable(payload),
            }
        )
        return record

    def _success_map(self, items: Sequence[_PlannedRecord]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            counts[item.event.event_id] = counts.get(item.event.event_id, 0) + 1
        return counts

    def _select_repository_method(self, kind: str, *, batch: bool) -> str | None:
        method_names = {
            "audit": ("save_audit_events", "save_audit_event"),
            "market": ("save_market_snapshots", "save_market_snapshot"),
            "account": ("save_account_snapshots", "save_account_snapshot"),
            "orderbook": ("save_orderbook_snapshots", "save_orderbook_snapshot"),
            "order": ("save_orders", "save_order"),
            "fill": ("save_fills", "save_fill"),
            "position": ("save_positions", "save_position"),
            "allocation": ("save_allocations", "save_allocation"),
            "outbox": ("save_outbox_events", "save_outbox_event"),
        }
        candidates = method_names.get(kind)
        if candidates is None:
            return None
        preferred = candidates[0] if batch else candidates[1]
        if self._repository is not None and hasattr(self._repository, preferred):
            return preferred
        fallback = candidates[1] if batch else candidates[0]
        if self._repository is not None and hasattr(self._repository, fallback):
            return fallback
        return None

    async def _invoke_repository_method(self, method_name: str, argument: Any) -> Any:
        if self._repository is None:
            raise RuntimeError("PersistenceWorker requires a repository")
        method = getattr(self._repository, method_name, None)
        if method is None:
            raise AttributeError(f"repository does not implement {method_name}")
        if inspect.iscoroutinefunction(method):
            return await method(argument)
        return await asyncio.to_thread(method, argument)

    def _format_error(self, kind: str, exc: BaseException) -> str:
        return f"{kind} write failed: {exc}"

    def _lag_ms(self, event: OutboxEvent) -> int:
        created_at = event.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delta = _utc_now() - created_at.astimezone(timezone.utc)
        return max(int(delta.total_seconds() * 1000), 0)

    def _outbox_depths(self) -> tuple[int, int, int]:
        if self._outbox is None:
            return 0, 0, 0

        snapshot = getattr(self._outbox, "snapshot", None)
        if callable(snapshot):
            with suppress(Exception):
                data = snapshot()
                outbox_depth = int(getattr(data, "depth", 0))
                retained_depth = int(getattr(data, "retained_depth", 0))
                dead_letter_depth = int(getattr(data, "dead_letter_depth", 0))
                if outbox_depth or retained_depth or dead_letter_depth:
                    return outbox_depth, retained_depth, dead_letter_depth

        ready = getattr(self._outbox, "_ready", None)
        retained = getattr(self._outbox, "_retained", None)
        dead_letters = getattr(self._outbox, "_dead_letters", None)
        outbox_depth = 0
        if ready is not None:
            with suppress(Exception):
                outbox_depth += ready.qsize()
        if retained is not None:
            with suppress(Exception):
                outbox_depth += len(retained)
        retained_depth = 0
        if retained is not None:
            with suppress(Exception):
                retained_depth = len(retained)
        dead_letter_depth = 0
        if dead_letters is not None:
            with suppress(Exception):
                dead_letter_depth = len(dead_letters)
        return outbox_depth, retained_depth, dead_letter_depth

    def _is_retryable_error(self, reason: str) -> bool:
        lowered = reason.lower()
        if "missing repository method" in lowered:
            return False
        if "validation" in lowered or "schema" in lowered:
            return False
        if "typeerror" in lowered or "valueerror" in lowered or "keyerror" in lowered:
            return False
        return True


def _is_retryable_error(reason: str) -> bool:
    lowered = reason.lower()
    if "missing repository method" in lowered:
        return False
    if "validation" in lowered or "schema" in lowered:
        return False
    if "typeerror" in lowered or "valueerror" in lowered or "keyerror" in lowered:
        return False
    return True
