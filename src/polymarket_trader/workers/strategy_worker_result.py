from __future__ import annotations

from dataclasses import dataclass

from polymarket_trader.app.strategy_service import StrategyEntryPlan
from polymarket_trader.app.trading_service import TradingReviewResult
from polymarket_trader.domain.events import DomainEvent
from polymarket_trader.domain.order import ManagedOrderIntent
from polymarket_trader.domain.state_machine import MarketLifecycle


@dataclass(frozen=True, slots=True)
class StrategyWorkerResult:
    entry_event: DomainEvent
    plan: StrategyEntryPlan | None
    review: TradingReviewResult | None
    emitted_event: DomainEvent
    emitted_events: tuple[DomainEvent, ...] = ()
    follow_up_intents: tuple[ManagedOrderIntent, ...] = ()
    follow_up_reviews: tuple[TradingReviewResult, ...] = ()
    state_before: MarketLifecycle | None = None
    state_after: MarketLifecycle | None = None
