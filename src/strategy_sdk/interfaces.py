from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from polymarket_trader.domain.market import Market

from strategy_sdk.models import (
    AccountSnapshotView,
    DiscoveryQuery,
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)
from strategy_sdk.ports import StrategyPorts


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


class StrategyFactory(Protocol):
    def __call__(
        self,
        *,
        ports: StrategyPorts | None = None,
        config_path: str | None = None,
    ) -> StrategyModule: ...


@dataclass(frozen=True, slots=True)
class StrategyManifest:
    module_path: str
    factory: StrategyFactory
