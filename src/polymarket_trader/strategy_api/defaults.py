from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.allocation import AllocationPlan
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


class PassiveStrategy:
    """Framework-safe default strategy used when no concrete strategy is wired."""

    def __init__(self) -> None:
        self._spec = StrategySpec(
            name="passive",
            version="1",
            description="Framework default strategy placeholder",
            capabilities=("discovery", "universe", "sizing", "entry", "exit", "recovery"),
        )

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    def build_discovery_queries(self) -> tuple[DiscoveryQuery, ...]:
        return ()

    def select_market(self, market: Market) -> UniverseDecision:
        return UniverseDecision.include(reason="framework_default")

    def size_entry(self, context: StrategyContext) -> EntrySizing:
        total_budget_usdc = _metadata_decimal(context, "portfolio_budget_usdc") or Decimal("0")
        return EntrySizing(
            allocation_plan=AllocationPlan(
                trace_id=context.trace_id,
                total_budget_usdc=total_budget_usdc,
                reason="strategy_not_configured",
            ),
            reason="strategy_not_configured",
        )

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.skip(reason="strategy_not_configured")

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.skip(reason="strategy_not_configured")

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        return RecoveryDecision(reason="strategy_not_configured")


def _metadata_decimal(context: StrategyContext, *keys: str) -> Decimal | None:
    for key in keys:
        value = context.metadata.get(key)
        if value is None:
            continue
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except Exception:
            return None
    return None
