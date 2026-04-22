from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import inf
from threading import RLock
from typing import Any, Mapping

from polymarket_trader.serialization import jsonable

DEFAULT_LATENCY_BUCKETS_MS: tuple[float, ...] = (
    1.0,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
    inf,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime | None = None) -> datetime:
    value = value or _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_labels(labels: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


class JsonSerializable:
    def as_dict(self) -> dict[str, Any]:
        return jsonable(self)


@dataclass(slots=True)
class Gauge(JsonSerializable):
    name: str
    value: float = 0.0
    labels: tuple[tuple[str, str], ...] = ()
    updated_at: datetime = field(default_factory=_utc_now)

    def set(self, value: float, *, updated_at: datetime | None = None) -> None:
        self.value = float(value)
        self.updated_at = _normalize_datetime(updated_at)

    def snapshot(self) -> GaugeSnapshot:
        return GaugeSnapshot(
            name=self.name,
            value=self.value,
            labels=self.labels,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class GaugeSnapshot(JsonSerializable):
    name: str
    value: float
    labels: tuple[tuple[str, str], ...]
    updated_at: datetime


@dataclass(slots=True)
class Counter(JsonSerializable):
    name: str
    value: float = 0.0
    labels: tuple[tuple[str, str], ...] = ()
    updated_at: datetime = field(default_factory=_utc_now)

    def inc(self, amount: float = 1.0, *, updated_at: datetime | None = None) -> None:
        self.value += float(amount)
        self.updated_at = _normalize_datetime(updated_at)

    def snapshot(self) -> CounterSnapshot:
        return CounterSnapshot(
            name=self.name,
            value=self.value,
            labels=self.labels,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class CounterSnapshot(JsonSerializable):
    name: str
    value: float
    labels: tuple[tuple[str, str], ...]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HistogramBucketSnapshot(JsonSerializable):
    upper_bound_ms: float | None
    count: int


@dataclass(frozen=True, slots=True)
class HistogramSnapshot(JsonSerializable):
    name: str
    labels: tuple[tuple[str, str], ...]
    count: int
    sum_ms: float
    min_ms: float | None
    max_ms: float | None
    mean_ms: float | None
    last_ms: float | None
    buckets: tuple[HistogramBucketSnapshot, ...]
    updated_at: datetime


@dataclass(slots=True)
class Histogram(JsonSerializable):
    name: str
    buckets_ms: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS_MS
    labels: tuple[tuple[str, str], ...] = ()
    count: int = 0
    sum_ms: float = 0.0
    min_ms: float | None = None
    max_ms: float | None = None
    last_ms: float | None = None
    bucket_counts: list[int] = field(default_factory=list)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.bucket_counts:
            self.bucket_counts = [0 for _ in self.buckets_ms]

    def observe(self, value_ms: float, *, updated_at: datetime | None = None) -> None:
        value_ms = float(value_ms)
        if value_ms < 0:
            value_ms = 0.0
        self.count += 1
        self.sum_ms += value_ms
        self.last_ms = value_ms
        self.min_ms = value_ms if self.min_ms is None else min(self.min_ms, value_ms)
        self.max_ms = value_ms if self.max_ms is None else max(self.max_ms, value_ms)
        self.updated_at = _normalize_datetime(updated_at)
        for index, upper_bound in enumerate(self.buckets_ms):
            if value_ms <= upper_bound:
                self.bucket_counts[index] += 1
                break

    def snapshot(self) -> HistogramSnapshot:
        mean_ms = self.sum_ms / self.count if self.count else None
        buckets = tuple(
            HistogramBucketSnapshot(
                upper_bound_ms=None if upper_bound == inf else upper_bound,
                count=count,
            )
            for upper_bound, count in zip(self.buckets_ms, self.bucket_counts, strict=False)
        )
        return HistogramSnapshot(
            name=self.name,
            labels=self.labels,
            count=self.count,
            sum_ms=self.sum_ms,
            min_ms=self.min_ms,
            max_ms=self.max_ms,
            mean_ms=mean_ms,
            last_ms=self.last_ms,
            buckets=buckets,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class QueueDepthSnapshot(JsonSerializable):
    name: str
    depth: int
    capacity: int
    retained_depth: int
    paused: bool
    updated_at: datetime


@dataclass(slots=True)
class QueueDepthState(JsonSerializable):
    name: str
    depth: int = 0
    capacity: int = 0
    retained_depth: int = 0
    paused: bool = False
    updated_at: datetime = field(default_factory=_utc_now)

    def snapshot(self) -> QueueDepthSnapshot:
        return QueueDepthSnapshot(
            name=self.name,
            depth=self.depth,
            capacity=self.capacity,
            retained_depth=self.retained_depth,
            paused=self.paused,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class WebSocketStateSnapshot(JsonSerializable):
    name: str
    connected: bool
    subscribed_count: int
    last_message_at: datetime | None
    last_message_lag_ms: float | None
    last_event_type: str | None
    last_error: str | None
    reconnect_attempts: int
    updated_at: datetime


@dataclass(slots=True)
class WebSocketState(JsonSerializable):
    name: str
    connected: bool = False
    subscribed_count: int = 0
    last_message_at: datetime | None = None
    last_message_lag_ms: float | None = None
    last_event_type: str | None = None
    last_error: str | None = None
    reconnect_attempts: int = 0
    updated_at: datetime = field(default_factory=_utc_now)

    def snapshot(self) -> WebSocketStateSnapshot:
        return WebSocketStateSnapshot(
            name=self.name,
            connected=self.connected,
            subscribed_count=self.subscribed_count,
            last_message_at=self.last_message_at,
            last_message_lag_ms=self.last_message_lag_ms,
            last_event_type=self.last_event_type,
            last_error=self.last_error,
            reconnect_attempts=self.reconnect_attempts,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class ReconcileSnapshot(JsonSerializable):
    last_started_at: datetime | None
    last_completed_at: datetime | None
    last_duration_ms: float | None
    last_status: str | None
    last_error: str | None
    last_trace_id: str | None
    last_actions: int
    updated_at: datetime


@dataclass(slots=True)
class ReconcileState(JsonSerializable):
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_duration_ms: float | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_trace_id: str | None = None
    last_actions: int = 0
    updated_at: datetime = field(default_factory=_utc_now)

    def snapshot(self) -> ReconcileSnapshot:
        return ReconcileSnapshot(
            last_started_at=self.last_started_at,
            last_completed_at=self.last_completed_at,
            last_duration_ms=self.last_duration_ms,
            last_status=self.last_status,
            last_error=self.last_error,
            last_trace_id=self.last_trace_id,
            last_actions=self.last_actions,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class TradingGateSnapshot(JsonSerializable):
    enabled: bool
    reason: str | None
    source: str | None
    updated_at: datetime


@dataclass(slots=True)
class TradingGateState(JsonSerializable):
    enabled: bool = False
    reason: str | None = None
    source: str | None = None
    updated_at: datetime = field(default_factory=_utc_now)

    def snapshot(self) -> TradingGateSnapshot:
        return TradingGateSnapshot(
            enabled=self.enabled,
            reason=self.reason,
            source=self.source,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class TimestampSnapshot(JsonSerializable):
    name: str
    at: datetime
    age_ms: float


@dataclass(frozen=True, slots=True)
class MetricsSnapshot(JsonSerializable):
    collected_at: datetime
    queue_depths: tuple[QueueDepthSnapshot, ...]
    ws_states: tuple[WebSocketStateSnapshot, ...]
    reconcile: ReconcileSnapshot | None
    trading_gate: TradingGateSnapshot
    counters: tuple[CounterSnapshot, ...]
    gauges: tuple[GaugeSnapshot, ...]
    histograms: tuple[HistogramSnapshot, ...]
    timestamps: tuple[TimestampSnapshot, ...]


class MetricsRegistry:
    """In-memory metrics registry for hot-path snapshots.

    The registry is intentionally small and lock-based. Writers stay cheap and
    readers get immutable snapshots that can be consumed by Supervisor, Admin
    API, or health/readiness code without touching external systems.
    """

    def __init__(self, *, latency_buckets_ms: tuple[float, ...] = DEFAULT_LATENCY_BUCKETS_MS) -> None:
        self._latency_buckets_ms = latency_buckets_ms
        self._lock = RLock()
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], Gauge] = {}
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], Counter] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}
        self._queue_depths: dict[str, QueueDepthState] = {}
        self._ws_states: dict[str, WebSocketState] = {}
        self._timestamps: dict[str, datetime] = {}
        self._reconcile: ReconcileState = ReconcileState()
        self._trading_gate: TradingGateState = TradingGateState()

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: Mapping[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> GaugeSnapshot:
        key = (name, _normalize_labels(labels))
        with self._lock:
            gauge = self._gauges.get(key)
            if gauge is None:
                gauge = Gauge(name=name, labels=key[1])
                self._gauges[key] = gauge
            gauge.set(value, updated_at=updated_at)
            return gauge.snapshot()

    def inc_counter(
        self,
        name: str,
        amount: float = 1.0,
        *,
        labels: Mapping[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> CounterSnapshot:
        key = (name, _normalize_labels(labels))
        with self._lock:
            counter = self._counters.get(key)
            if counter is None:
                counter = Counter(name=name, labels=key[1])
                self._counters[key] = counter
            counter.inc(amount, updated_at=updated_at)
            return counter.snapshot()

    def observe_latency(
        self,
        name: str,
        value_ms: float,
        *,
        labels: Mapping[str, Any] | None = None,
        updated_at: datetime | None = None,
    ) -> HistogramSnapshot:
        key = (name, _normalize_labels(labels))
        with self._lock:
            histogram = self._histograms.get(key)
            if histogram is None:
                histogram = Histogram(
                    name=name,
                    buckets_ms=self._latency_buckets_ms,
                    labels=key[1],
                )
                self._histograms[key] = histogram
            histogram.observe(value_ms, updated_at=updated_at)
            return histogram.snapshot()

    def set_queue_depth(
        self,
        name: str,
        depth: int,
        *,
        capacity: int = 0,
        retained_depth: int = 0,
        paused: bool = False,
        updated_at: datetime | None = None,
    ) -> QueueDepthSnapshot:
        with self._lock:
            state = self._queue_depths.get(name)
            if state is None:
                state = QueueDepthState(name=name)
                self._queue_depths[name] = state
            state.depth = max(0, int(depth))
            state.capacity = max(0, int(capacity))
            state.retained_depth = max(0, int(retained_depth))
            state.paused = bool(paused)
            state.updated_at = _normalize_datetime(updated_at)
            return state.snapshot()

    def set_ws_state(
        self,
        name: str,
        *,
        connected: bool,
        subscribed_count: int = 0,
        last_message_at: datetime | None = None,
        last_message_lag_ms: float | None = None,
        last_event_type: str | None = None,
        last_error: str | None = None,
        reconnect_attempts: int = 0,
        updated_at: datetime | None = None,
    ) -> WebSocketStateSnapshot:
        with self._lock:
            state = self._ws_states.get(name)
            if state is None:
                state = WebSocketState(name=name)
                self._ws_states[name] = state
            state.connected = bool(connected)
            state.subscribed_count = max(0, int(subscribed_count))
            state.last_message_at = _normalize_datetime(last_message_at) if last_message_at else None
            state.last_message_lag_ms = None if last_message_lag_ms is None else float(last_message_lag_ms)
            state.last_event_type = last_event_type
            state.last_error = last_error
            state.reconnect_attempts = max(0, int(reconnect_attempts))
            state.updated_at = _normalize_datetime(updated_at)
            return state.snapshot()

    def mark_timestamp(
        self,
        name: str,
        *,
        at: datetime | None = None,
    ) -> TimestampSnapshot:
        at = _normalize_datetime(at)
        with self._lock:
            self._timestamps[name] = at
            return TimestampSnapshot(
                name=name,
                at=at,
                age_ms=0.0,
            )

    def record_reconcile(
        self,
        duration_ms: float | None,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        status: str | None = None,
        error: str | None = None,
        trace_id: str | None = None,
        actions: int = 0,
    ) -> ReconcileSnapshot:
        completed_at = _normalize_datetime(completed_at)
        started_at = _normalize_datetime(started_at) if started_at is not None else None
        with self._lock:
            self._reconcile.last_started_at = started_at
            self._reconcile.last_completed_at = completed_at
            self._reconcile.last_duration_ms = None if duration_ms is None else float(duration_ms)
            self._reconcile.last_status = status
            self._reconcile.last_error = error
            self._reconcile.last_trace_id = trace_id
            self._reconcile.last_actions = max(0, int(actions))
            self._reconcile.updated_at = completed_at
            if duration_ms is not None:
                self.observe_latency("reconcile_duration_ms", duration_ms, updated_at=completed_at)
            return self._reconcile.snapshot()

    def set_trading_gate(
        self,
        enabled: bool,
        *,
        reason: str | None = None,
        source: str | None = None,
        updated_at: datetime | None = None,
    ) -> TradingGateSnapshot:
        with self._lock:
            self._trading_gate.enabled = bool(enabled)
            self._trading_gate.reason = reason
            self._trading_gate.source = source
            self._trading_gate.updated_at = _normalize_datetime(updated_at)
            return self._trading_gate.snapshot()

    def queue_depth(self, name: str) -> QueueDepthSnapshot | None:
        with self._lock:
            state = self._queue_depths.get(name)
            return None if state is None else state.snapshot()

    def ws_state(self, name: str) -> WebSocketStateSnapshot | None:
        with self._lock:
            state = self._ws_states.get(name)
            return None if state is None else state.snapshot()

    def reconcile_snapshot(self) -> ReconcileSnapshot:
        with self._lock:
            return self._reconcile.snapshot()

    def trading_gate_snapshot(self) -> TradingGateSnapshot:
        with self._lock:
            return self._trading_gate.snapshot()

    def snapshot(self) -> MetricsSnapshot:
        collected_at = _utc_now()
        with self._lock:
            queue_depths = tuple(
                state.snapshot() for state in sorted(self._queue_depths.values(), key=lambda item: item.name)
            )
            ws_states = tuple(
                state.snapshot() for state in sorted(self._ws_states.values(), key=lambda item: item.name)
            )
            counters = tuple(
                CounterSnapshot(
                    name=counter.name,
                    value=counter.value,
                    labels=counter.labels,
                    updated_at=counter.updated_at,
                )
                for counter in sorted(self._counters.values(), key=lambda item: (item.name, item.labels))
            )
            gauges = tuple(
                GaugeSnapshot(
                    name=gauge.name,
                    value=gauge.value,
                    labels=gauge.labels,
                    updated_at=gauge.updated_at,
                )
                for gauge in sorted(self._gauges.values(), key=lambda item: (item.name, item.labels))
            )
            histograms = tuple(
                histogram.snapshot()
                for histogram in sorted(self._histograms.values(), key=lambda item: (item.name, item.labels))
            )
            timestamps = tuple(
                TimestampSnapshot(
                    name=name,
                    at=at,
                    age_ms=max(0.0, (collected_at - at).total_seconds() * 1000.0),
                )
                for name, at in sorted(self._timestamps.items())
            )
            return MetricsSnapshot(
                collected_at=collected_at,
                queue_depths=queue_depths,
                ws_states=ws_states,
                reconcile=self._reconcile.snapshot(),
                trading_gate=self._trading_gate.snapshot(),
                counters=counters,
                gauges=gauges,
                histograms=histograms,
                timestamps=timestamps,
            )


__all__ = [
    "Counter",
    "CounterSnapshot",
    "DEFAULT_LATENCY_BUCKETS_MS",
    "Gauge",
    "GaugeSnapshot",
    "Histogram",
    "HistogramBucketSnapshot",
    "HistogramSnapshot",
    "JsonSerializable",
    "MetricsRegistry",
    "MetricsSnapshot",
    "QueueDepthSnapshot",
    "ReconcileSnapshot",
    "TimestampSnapshot",
    "TradingGateSnapshot",
    "WebSocketStateSnapshot",
]
