from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

from polymarket_trader.domain.market import Market
from polymarket_trader.extension_api.commands import ExtensionCommand
from polymarket_trader.extension_api.context import AccountSnapshotView, StrategyContext
from polymarket_trader.extension_api.decisions import (
    DiscoveryQuery,
    EntrySizing,
    RecoveryDecision,
    StrategyDecision,
    UniverseDecision,
)


@dataclass(frozen=True, slots=True)
class HookResult:
    commands: tuple[ExtensionCommand, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class ExtensionHooks(Protocol):
    def build_discovery_queries(self) -> tuple[DiscoveryQuery, ...]: ...

    def select_market(self, market: Market) -> UniverseDecision: ...

    def size_entry(self, context: StrategyContext) -> EntrySizing: ...

    def decide_entry(self, context: StrategyContext) -> StrategyDecision: ...

    def decide_exit(self, context: StrategyContext) -> StrategyDecision: ...

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision: ...

    def decide_follow_up(self, context: StrategyContext) -> tuple[StrategyDecision, ...]: ...

    def should_keep_tracking(
        self,
        market: Market,
        account_snapshot: AccountSnapshotView | None,
    ) -> bool: ...

    def build_filtered_tracking_market(
        self,
        candidate_market: Market,
        *,
        existing_market: Market,
        reason: str,
    ) -> Market: ...
