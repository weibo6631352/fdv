from __future__ import annotations

from dataclasses import dataclass

from fdv_trader.domain.order import OrderIntent


@dataclass(frozen=True, slots=True)
class RiskDecision:
    passed: bool
    reason: str = ""


class RiskManager:
    """Mandatory gate before any order intent reaches the executor."""

    def check_order_intent(self, intent: OrderIntent) -> RiskDecision:
        if intent.amount_usdc is None and intent.size_shares is None:
            return RiskDecision(False, "missing_order_size")
        return RiskDecision(True, "passed")

