from __future__ import annotations

from typing import Protocol, runtime_checkable

from polymarket_trader.domain.market import Market
from polymarket_trader.strategy_api.models import (
    DiscoveryQuery,
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)


@runtime_checkable
class StrategyModule(Protocol):
    @property
    def spec(self) -> StrategySpec: ...

    def build_discovery_queries(self) -> tuple[DiscoveryQuery, ...]: ...

    def select_market(self, market: Market) -> UniverseDecision: ...

    def size_entry(self, context: StrategyContext) -> EntrySizing: ...

    def decide_entry(self, context: StrategyContext) -> StrategyDecision: ...

    def decide_exit(self, context: StrategyContext) -> StrategyDecision: ...

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision: ...
