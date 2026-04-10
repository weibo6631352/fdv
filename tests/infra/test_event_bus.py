from __future__ import annotations

import asyncio

from fdv_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from fdv_trader.runtime.event_bus import EventBus


def _event(
    *,
    trace_id: str,
    event_id: str,
    event_type: DomainEventType,
    reason: str,
) -> DomainEvent:
    return DomainEvent(
        trace_id=trace_id,
        event_type=event_type,
        event_id=event_id,
        reason=reason,
    )


def test_event_bus_prioritizes_trading_and_restores_retained_low_priority_events() -> None:
    async def run() -> None:
        bus = EventBus(
            trading_capacity=2,
            maintenance_capacity=1,
            persistence_capacity=1,
            retained_capacity=4,
        )
        bus.pause_low_priority()

        maintenance_event = _event(
            trace_id="trace-maintenance",
            event_id="event-maintenance",
            event_type=DomainEventType.MARKET_UPDATED,
            reason="maintenance",
        )
        persistence_event = _event(
            trace_id="trace-persistence",
            event_id="event-persistence",
            event_type=DomainEventType.RETRY,
            reason="persistence",
        )
        trading_event = _event(
            trace_id="trace-trading",
            event_id="event-trading",
            event_type=DomainEventType.RISK_CHECK_PASSED,
            reason="trading",
        )

        await bus.publish(OutboxPriority.P2, maintenance_event)
        await bus.publish(OutboxPriority.P3, persistence_event)
        await bus.publish(OutboxPriority.P0, trading_event)

        paused_snapshot = bus.snapshot()
        assert paused_snapshot.low_priority_paused is True
        assert paused_snapshot.trading_queue_depth == 1
        assert paused_snapshot.maintenance_retained_depth == 1
        assert paused_snapshot.persistence_retained_depth == 1

        assert await bus.next_event() == trading_event

        await bus.resume_low_priority()
        resumed_snapshot = bus.snapshot()
        assert resumed_snapshot.low_priority_paused is False
        assert resumed_snapshot.maintenance_retained_depth == 0
        assert resumed_snapshot.persistence_retained_depth == 0

        assert await bus.next_event() == maintenance_event
        assert await bus.next_event() == persistence_event

        final_snapshot = bus.snapshot()
        assert final_snapshot.trading_queue_depth == 0
        assert final_snapshot.maintenance_queue_depth == 0
        assert final_snapshot.persistence_queue_depth == 0

    asyncio.run(run())
