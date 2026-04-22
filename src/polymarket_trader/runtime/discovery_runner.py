from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable
from uuid import uuid4

_MARKET_DISCOVERY_EVENT_PAGE_LIMIT = 50
_MARKET_DISCOVERY_MARKET_BUDGET_PER_TICK = 1000
_MARKET_DISCOVERY_REQUEST_BUDGET_PER_TICK = 2
_MARKET_DISCOVERY_MAX_RUNTIME_MS = 200.0
MARKET_DISCOVERY_TICK_SECONDS = 0.5
MARKET_DISCOVERY_RETRY_BACKOFF_SECONDS = 5

logger = logging.getLogger(__name__)
RuntimeMetricsSync = Callable[[Any], None]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sync(sync_runtime_metrics: RuntimeMetricsSync | None, runtime: Any) -> None:
    if sync_runtime_metrics is not None:
        sync_runtime_metrics(runtime)


@dataclass(slots=True)
class FullMarketDiscoveryState:
    after_cursor: str | None = None
    round_id: int = 1
    round_started_at: datetime | None = None
    last_round_completed_at: datetime | None = None
    last_completed_round_pages: int = 0
    last_completed_round_markets: int = 0
    last_page_size: int = 0
    pages_scanned_in_round: int = 0
    markets_seen_in_round: int = 0
    last_tick_started_at: datetime | None = None
    last_tick_completed_at: datetime | None = None
    last_tick_requests: int = 0
    last_tick_markets: int = 0
    last_error: str | None = None
    consecutive_failures: int = 0

    def start_tick(self) -> None:
        self.last_tick_started_at = _utc_now()
        self.last_tick_completed_at = None
        self.last_tick_requests = 0
        self.last_tick_markets = 0
        if self.round_started_at is None:
            self.round_started_at = self.last_tick_started_at

    def record_page(self, *, page_size: int, next_cursor: str | None) -> None:
        self.last_page_size = max(0, int(page_size))
        self.pages_scanned_in_round += 1
        self.markets_seen_in_round += max(0, int(page_size))
        self.last_tick_requests += 1
        self.last_tick_markets += max(0, int(page_size))
        self.after_cursor = next_cursor
        self.last_error = None
        self.consecutive_failures = 0

    def finish_round(self) -> None:
        self.after_cursor = None
        self.last_completed_round_pages = self.pages_scanned_in_round
        self.last_completed_round_markets = self.markets_seen_in_round
        self.last_round_completed_at = _utc_now()
        self.round_id += 1
        self.round_started_at = None
        self.pages_scanned_in_round = 0
        self.markets_seen_in_round = 0

    def finish_tick(self) -> None:
        self.last_tick_completed_at = _utc_now()

    def record_failure(self, reason: str) -> None:
        self.last_error = reason
        self.consecutive_failures += 1
        self.last_tick_completed_at = _utc_now()


async def run_market_discovery_scan(
    runtime: Any,
    *,
    sync_runtime_metrics: RuntimeMetricsSync | None = None,
) -> None:
    state = runtime.market_discovery_scan
    if (
        runtime.market_discovery_worker.last_failure is not None
        and not runtime.market_discovery_worker.should_retry()
    ):
        retry_at = runtime.market_discovery_worker.last_failure.retry_at.isoformat()
        runtime.supervisor.heartbeat_worker(
            "market_discovery",
            detail=f"retry_backoff until={retry_at}",
        )
        _sync(sync_runtime_metrics, runtime)
        return

    state.start_tick()
    runtime.supervisor.heartbeat_worker(
        "market_discovery",
        detail=(
            f"round={state.round_id} cursor={'set' if state.after_cursor else 'start'} "
            f"budget={_MARKET_DISCOVERY_REQUEST_BUDGET_PER_TICK}"
        ),
    )
    started_at = asyncio.get_running_loop().time()
    try:
        round_completed = False
        completed_round_id: int | None = None
        completed_round_pages = 0
        completed_round_markets = 0
        while (
            state.last_tick_requests < _MARKET_DISCOVERY_REQUEST_BUDGET_PER_TICK
            and state.last_tick_markets < _MARKET_DISCOVERY_MARKET_BUDGET_PER_TICK
        ):
            elapsed_ms = (asyncio.get_running_loop().time() - started_at) * 1000.0
            if elapsed_ms >= _MARKET_DISCOVERY_MAX_RUNTIME_MS:
                break
            page_markets, next_cursor = await fetch_full_market_discovery_page(runtime)
            runtime.market_discovery_worker.mark_scan_success()
            market_payloads = tuple(raw_event.payload for raw_event in page_markets)
            state.record_page(page_size=len(market_payloads), next_cursor=next_cursor)
            runtime.metrics.inc_counter("market_discovery_requests_total", 1.0)
            runtime.metrics.inc_counter("market_discovery_pages_scanned_total", 1.0)
            if market_payloads:
                runtime.metrics.inc_counter(
                    "market_discovery_markets_scanned_total",
                    float(len(market_payloads)),
                )

            await runtime.market_discovery_worker.ingest_source_page(
                {"markets": list(market_payloads)},
                source="gamma.events_keyset",
                trace_id=f"market-discovery-round-{state.round_id}-{uuid4().hex}",
            )
            if next_cursor is None:
                round_completed = True
                completed_round_id = state.round_id
                completed_round_pages = state.pages_scanned_in_round
                completed_round_markets = state.markets_seen_in_round
                state.finish_round()
                runtime.metrics.inc_counter("market_discovery_rounds_completed_total", 1.0)
                break
            if state.last_tick_markets >= _MARKET_DISCOVERY_MARKET_BUDGET_PER_TICK:
                break
    except Exception as exc:  # pragma: no cover - depends on external gamma
        state.record_failure(str(exc))
        runtime.market_discovery_worker.record_failure(
            source="gamma.events_keyset",
            reason=str(exc),
            retry_after_seconds=MARKET_DISCOVERY_RETRY_BACKOFF_SECONDS,
        )
        runtime.supervisor.mark_worker_error(
            "market_discovery",
            detail="discover_failed",
            last_error=str(exc),
        )
        logger.warning("market discovery scan failed", extra={"reason": str(exc)})
    else:
        state.finish_tick()
        if round_completed and completed_round_id is not None:
            runtime.supervisor.heartbeat_worker(
                "market_discovery",
                detail=(
                    f"round_completed={completed_round_id} "
                    f"pages={completed_round_pages} markets={completed_round_markets}"
                ),
            )
        else:
            runtime.supervisor.heartbeat_worker(
                "market_discovery",
                detail=(
                    f"round={state.round_id} reqs={state.last_tick_requests} "
                    f"markets={state.last_tick_markets} cursor={'set' if state.after_cursor else 'start'}"
                ),
            )
    finally:
        _sync(sync_runtime_metrics, runtime)


async def fetch_full_market_discovery_page(runtime: Any) -> tuple[tuple[Any, ...], str | None]:
    params: dict[str, Any] = {
        "active": True,
        "closed": False,
        "limit": _MARKET_DISCOVERY_EVENT_PAGE_LIMIT,
    }
    if runtime.market_discovery_scan.after_cursor is not None:
        params["after_cursor"] = runtime.market_discovery_scan.after_cursor
    events, next_cursor = await runtime.gamma_client.list_events_keyset_by_params(params)
    raw_events: list[Any] = []
    for event in events:
        raw_events.extend(event.to_raw_market_events(source="gamma.events_keyset"))
    return tuple(raw_events), next_cursor
