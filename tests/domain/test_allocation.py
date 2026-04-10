from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.allocation import equal_weight_budget


def test_equal_weight_budget_returns_zero_without_eligible_markets() -> None:
    assert equal_weight_budget(Decimal("100"), 0) == Decimal("0")

