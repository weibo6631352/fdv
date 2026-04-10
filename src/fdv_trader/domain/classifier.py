from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fdv_trader.domain.constants import CRYPTO_KEYWORDS, EXCLUDED_THRESHOLD_KEYWORDS


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    accepted: bool
    reason: str
    matched_keywords: tuple[str, ...] = ()


class MarketClassifier:
    """Classifies raw Polymarket market data into target or rejected markets."""

    def classify(self, raw_market: Mapping[str, Any]) -> ClassificationResult:
        category_text = self._join_text(raw_market, "category", "categories", "tags").lower()
        event_text = self._join_text(raw_market, "event_title", "eventTitle", "title").lower()
        market_text = self._join_text(
            raw_market,
            "market_question",
            "question",
            "market_slug",
            "slug",
            "description",
        ).lower()

        if not any(keyword in category_text for keyword in CRYPTO_KEYWORDS):
            return ClassificationResult(False, "missing_crypto_category")
        if "fdv" not in event_text and "fully diluted valuation" not in event_text:
            return ClassificationResult(False, "missing_fdv_event")
        if not any(keyword in market_text for keyword in ("500m", "$500m", "500 million")):
            return ClassificationResult(False, "missing_500m_threshold")
        if any(keyword in market_text for keyword in EXCLUDED_THRESHOLD_KEYWORDS):
            return ClassificationResult(False, "excluded_threshold")
        return ClassificationResult(True, "accepted", ("crypto", "fdv", "500m"))

    @staticmethod
    def _join_text(raw_market: Mapping[str, Any], *keys: str) -> str:
        values = []
        for key in keys:
            value = raw_market.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value)
            elif value is not None:
                values.append(str(value))
        return " ".join(values)

