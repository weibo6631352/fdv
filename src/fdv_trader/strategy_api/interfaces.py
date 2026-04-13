from __future__ import annotations

from typing import Protocol, runtime_checkable

from fdv_trader.domain.market import Market
from fdv_trader.strategy_api.models import (
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)


@runtime_checkable
class UniverseSelector(Protocol):
    def select_market(self, market: Market) -> UniverseDecision: ...


@runtime_checkable
class EntryPolicy(Protocol):
    def decide_entry(self, context: StrategyContext) -> StrategyDecision: ...


@runtime_checkable
class SizingPolicy(Protocol):
    def size_entry(self, context: StrategyContext) -> StrategyDecision: ...


@runtime_checkable
class ExitPolicy(Protocol):
    def decide_exit(self, context: StrategyContext) -> StrategyDecision: ...


@runtime_checkable
class RecoveryPolicy(Protocol):
    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision: ...


@runtime_checkable
class StrategyModule(Protocol):
    @property
    def spec(self) -> StrategySpec: ...

    def select_market(self, market: Market) -> UniverseDecision: ...

    def decide_entry(self, context: StrategyContext) -> StrategyDecision: ...

    def decide_exit(self, context: StrategyContext) -> StrategyDecision: ...

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision: ...
