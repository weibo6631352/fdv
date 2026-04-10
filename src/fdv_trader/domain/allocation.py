from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class MarketAllocation:
    condition_id: str
    target_budget_usdc: Decimal
    buy_budget_usdc: Decimal
    reason: str = ""


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    trace_id: str
    total_budget_usdc: Decimal
    allocations: tuple[MarketAllocation, ...] = field(default_factory=tuple)


def equal_weight_budget(portfolio_budget_usdc: Decimal, eligible_market_count: int) -> Decimal:
    if eligible_market_count <= 0:
        return Decimal("0")
    return portfolio_budget_usdc / Decimal(eligible_market_count)

