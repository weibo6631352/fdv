from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TemplateStrategyConfig:
    required_category: str | None = "Crypto"
    required_keywords: tuple[str, ...] = ("template",)
    entry_price_max: Decimal = Decimal("0.60")
    exit_price: Decimal = Decimal("0.70")
