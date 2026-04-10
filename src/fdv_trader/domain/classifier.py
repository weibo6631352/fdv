from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

from fdv_trader.domain.events import DomainEvent, DomainEventType
from fdv_trader.domain.market import Market, TradingStatus


class ClassificationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ClassificationRejectReason(StrEnum):
    NOT_CRYPTO = "not_crypto"
    MISSING_FDV_TITLE = "missing_fdv_title"
    MISSING_500M_MARKET_FIELD = "missing_500m_market_field"
    NON_TARGET_THRESHOLD = "non_target_threshold"
    MISSING_TRADING_CONDITIONS = "missing_trading_conditions"
    FIELD_PARSE_FAILED = "field_parse_failed"
    RESOLUTION_CONDITION_EXCEPTION = "resolution_condition_exception"


@dataclass(frozen=True, slots=True)
class MatchSignal:
    field_name: str
    keyword: str


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    status: ClassificationStatus
    condition_id: str | None
    yes_token_id: str | None
    no_token_id: str | None
    tick_size: Decimal | None
    min_order_size: Decimal | None
    neg_risk: bool
    category: str | None
    tags: tuple[str, ...]
    market_slug: str | None
    event_title: str | None
    event_slug: str | None
    event_id: str | None
    matched_fields: tuple[str, ...] = field(default_factory=tuple)
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    reject_reason: ClassificationRejectReason | None = None
    reject_detail: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is ClassificationStatus.ACCEPTED

    @property
    def event_type(self) -> DomainEventType:
        return (
            DomainEventType.MARKET_FILTERED_IN
            if self.accepted
            else DomainEventType.MARKET_FILTERED_OUT
        )

    def to_event(
        self,
        *,
        trace_id: str,
        event_id: str,
        created_at: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> DomainEvent:
        payload_data: dict[str, Any] = {
            "accepted": self.accepted,
            "status": self.status.value,
            "condition_id": self.condition_id,
            "yes_token_id": self.yes_token_id,
            "no_token_id": self.no_token_id,
            "tick_size": self.tick_size,
            "min_order_size": self.min_order_size,
            "neg_risk": self.neg_risk,
            "category": self.category,
            "tags": self.tags,
            "market_slug": self.market_slug,
            "event_title": self.event_title,
            "event_slug": self.event_slug,
            "event_id": self.event_id,
            "matched_fields": self.matched_fields,
            "matched_keywords": self.matched_keywords,
            "reject_reason": self.reject_reason.value if self.reject_reason else None,
            "reject_detail": self.reject_detail,
        }
        if payload:
            payload_data.update(payload)
        return DomainEvent(
            trace_id=trace_id,
            event_type=self.event_type,
            event_id=event_id,
            market_slug=self.market_slug,
            condition_id=self.condition_id,
            reason=self.reject_reason.value if self.reject_reason else "",
            created_at=created_at or datetime.utcnow(),
            payload=payload_data,
        )

    def to_market(
        self,
        *,
        trading_status: TradingStatus = TradingStatus.ELIGIBLE,
    ) -> Market:
        if not self.accepted:
            raise ValueError("rejected classification cannot be converted to Market")
        if (
            self.condition_id is None
            or self.market_slug is None
            or self.no_token_id is None
            or self.tick_size is None
            or self.min_order_size is None
        ):
            raise ValueError("accepted classification is missing required market fields")
        return Market(
            condition_id=self.condition_id,
            market_slug=self.market_slug,
            no_token_id=self.no_token_id,
            yes_token_id=self.yes_token_id,
            event_id=self.event_id,
            event_title=self.event_title,
            event_slug=self.event_slug,
            tick_size=self.tick_size,
            min_order_size=self.min_order_size,
            neg_risk=self.neg_risk,
            category=self.category,
            tags=self.tags,
            matched_keywords=self.matched_keywords,
            trading_status=trading_status,
        )


@dataclass(frozen=True, slots=True)
class TargetMarketAccepted:
    classification: ClassificationResult
    trace_id: str
    event_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def event_type(self) -> DomainEventType:
        return DomainEventType.MARKET_FILTERED_IN

    def to_domain_event(self) -> DomainEvent:
        return self.classification.to_event(
            trace_id=self.trace_id,
            event_id=self.event_id,
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class TargetMarketRejected:
    classification: ClassificationResult
    trace_id: str
    event_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def event_type(self) -> DomainEventType:
        return DomainEventType.MARKET_FILTERED_OUT

    def to_domain_event(self) -> DomainEvent:
        return self.classification.to_event(
            trace_id=self.trace_id,
            event_id=self.event_id,
            created_at=self.created_at,
        )


class MarketClassifier:
    """Classify raw market payloads with pure text rules only."""

    _FDV_PATTERNS = (
        re.compile(r"\bfdv\b", re.IGNORECASE),
        re.compile(r"\bfully[-\s]+diluted\s+valuation\b", re.IGNORECASE),
    )
    _TARGET_THRESHOLD_PATTERNS = (
        re.compile(r"\$?500\s*m\b", re.IGNORECASE),
        re.compile(r"\b500\s*million\b", re.IGNORECASE),
        re.compile(r"\b500,?000,?000\b", re.IGNORECASE),
    )
    _EXCLUDED_THRESHOLD_PATTERNS = (
        re.compile(r"\$?150\s*m\b", re.IGNORECASE),
        re.compile(r"\b150\s*million\b", re.IGNORECASE),
        re.compile(r"\$?300\s*m\b", re.IGNORECASE),
        re.compile(r"\b300\s*million\b", re.IGNORECASE),
        re.compile(r"\$?800\s*m\b", re.IGNORECASE),
        re.compile(r"\b800\s*million\b", re.IGNORECASE),
        re.compile(r"\$?1\s*b\b", re.IGNORECASE),
        re.compile(r"\b1\s*billion\b", re.IGNORECASE),
        re.compile(r"\b1\s*bn\b", re.IGNORECASE),
        re.compile(r"\b1\.0\s*b\b", re.IGNORECASE),
        re.compile(r"\b1,?000,?000,?000\b", re.IGNORECASE),
    )

    def classify(self, raw_market: Mapping[str, Any]) -> ClassificationResult:
        parsed = self._parse_market_fields(raw_market)
        match_signals: list[MatchSignal] = []

        if parsed["parse_error"] is not None:
            return self._reject(
                ClassificationRejectReason.FIELD_PARSE_FAILED,
                parsed,
                match_signals,
                parsed["parse_error"],
            )

        # Crypto 是硬前置；Pre-Market 只能作为额外标签，不能替代 Crypto / Cryptocurrency 分类。
        category_text = " ".join(
            self._collect_text(raw_market, "category", "categories", "tags")
        ).lower()
        if not self._contains_any(category_text, ("crypto", "cryptocurrency")):
            return self._reject(
                ClassificationRejectReason.NOT_CRYPTO,
                parsed,
                match_signals,
                "category missing crypto / cryptocurrency keyword",
            )
        match_signals.extend(
            self._matched_signals("category", category_text, ("crypto", "cryptocurrency"))
        )

        # FDV 只允许从 event title 或其明确等价字段命中，不能把宽泛 valuation 当成目标信号。
        event_text = " ".join(
            self._collect_text(
                raw_market,
                "event_title",
                "eventTitle",
                "title",
                "event_name",
                "eventName",
            )
        ).lower()
        if not self._contains_fdv(event_text):
            return self._reject(
                ClassificationRejectReason.MISSING_FDV_TITLE,
                parsed,
                match_signals,
                "event title missing fdv / fully diluted valuation keyword",
            )
        match_signals.extend(
            self._matched_signals("event_title", event_text, ("fdv", "fully diluted valuation"))
        )

        # 500M 只从 question / name / slug 等 market 字段命中，避免 title 里的表述误导分类。
        market_text = " ".join(
            self._collect_text(
                raw_market,
                "question",
                "market_question",
                "name",
                "market_name",
                "slug",
                "market_slug",
            )
        ).lower()
        excluded_match = self._first_match(market_text, self._EXCLUDED_THRESHOLD_PATTERNS)
        if excluded_match is not None:
            return self._reject(
                ClassificationRejectReason.NON_TARGET_THRESHOLD,
                parsed,
                match_signals,
                f"market text matched excluded threshold keyword: {excluded_match}",
                matched_fields=(
                    "question",
                    "market_question",
                    "name",
                    "market_name",
                    "slug",
                    "market_slug",
                ),
                matched_keywords=(excluded_match,),
            )
        target_match = self._first_match(market_text, self._TARGET_THRESHOLD_PATTERNS)
        if target_match is None:
            return self._reject(
                ClassificationRejectReason.MISSING_500M_MARKET_FIELD,
                parsed,
                match_signals,
                "market question / name / slug missing 500m threshold keyword",
            )
        match_signals.extend(
            self._matched_signals(
                "market_question",
                market_text,
                ("$500m", "500m", "500 million", "500,000,000"),
            )
        )

        if (
            parsed["condition_id"] is None
            or parsed["market_slug"] is None
            or parsed["yes_token_id"] is None
            or parsed["no_token_id"] is None
        ):
            return self._reject(
                ClassificationRejectReason.MISSING_TRADING_CONDITIONS,
                parsed,
                match_signals,
                "missing condition_id / market_slug / yes_token_id / no_token_id",
            )

        if parsed["tick_size"] is None or parsed["min_order_size"] is None:
            return self._reject(
                ClassificationRejectReason.MISSING_TRADING_CONDITIONS,
                parsed,
                match_signals,
                "missing tick_size / min_order_size",
            )

        return ClassificationResult(
            status=ClassificationStatus.ACCEPTED,
            condition_id=parsed["condition_id"],
            yes_token_id=parsed["yes_token_id"],
            no_token_id=parsed["no_token_id"],
            tick_size=parsed["tick_size"],
            min_order_size=parsed["min_order_size"],
            neg_risk=parsed["neg_risk"],
            category=parsed["category"],
            tags=parsed["tags"],
            market_slug=parsed["market_slug"],
            event_title=parsed["event_title"],
            event_slug=parsed["event_slug"],
            event_id=parsed["event_id"],
            matched_fields=tuple(signal.field_name for signal in match_signals),
            matched_keywords=tuple(signal.keyword for signal in match_signals),
        )

    def _reject(
        self,
        reason: ClassificationRejectReason,
        parsed: Mapping[str, Any],
        match_signals: list[MatchSignal],
        reject_detail: str,
        *,
        matched_fields: tuple[str, ...] | None = None,
        matched_keywords: tuple[str, ...] | None = None,
    ) -> ClassificationResult:
        fields = matched_fields or tuple(signal.field_name for signal in match_signals)
        keywords = matched_keywords or tuple(signal.keyword for signal in match_signals)
        return ClassificationResult(
            status=ClassificationStatus.REJECTED,
            condition_id=parsed["condition_id"],
            yes_token_id=parsed["yes_token_id"],
            no_token_id=parsed["no_token_id"],
            tick_size=parsed["tick_size"],
            min_order_size=parsed["min_order_size"],
            neg_risk=parsed["neg_risk"],
            category=parsed["category"],
            tags=parsed["tags"],
            market_slug=parsed["market_slug"],
            event_title=parsed["event_title"],
            event_slug=parsed["event_slug"],
            event_id=parsed["event_id"],
            matched_fields=fields,
            matched_keywords=keywords,
            reject_reason=reason,
            reject_detail=reject_detail,
        )

    def _parse_market_fields(self, raw_market: Mapping[str, Any]) -> dict[str, Any]:
        try:
            condition_id = self._first_value(raw_market, "condition_id", "conditionId")
            yes_token_id = self._first_value(
                raw_market,
                "yes_token_id",
                "yesTokenId",
                "yes_token",
                "yesToken",
            )
            no_token_id = self._first_value(
                raw_market,
                "no_token_id",
                "noTokenId",
                "no_token",
                "noToken",
            )
            tick_size = self._parse_decimal(
                self._first_value(raw_market, "tick_size", "tickSize", "tick")
            )
            min_order_size = self._parse_decimal(
                self._first_value(
                    raw_market,
                    "min_order_size",
                    "minOrderSize",
                    "min_size",
                    "minSize",
                )
            )
            neg_risk = self._parse_bool(self._first_value(raw_market, "neg_risk", "negRisk"))
            category = self._first_value(raw_market, "category")
            tags = self._parse_tags(self._first_value(raw_market, "tags"))
            market_slug = self._first_value(raw_market, "market_slug", "slug")
            event_title = self._first_value(
                raw_market,
                "event_title",
                "eventTitle",
                "title",
                "event_name",
                "eventName",
            )
            event_slug = self._first_value(raw_market, "event_slug", "eventSlug")
            event_id = self._first_value(raw_market, "event_id", "eventId")
        except (TypeError, ValueError) as exc:
            return {
                "condition_id": None,
                "yes_token_id": None,
                "no_token_id": None,
                "tick_size": None,
                "min_order_size": None,
                "neg_risk": False,
                "category": None,
                "tags": tuple(),
                "market_slug": None,
                "event_title": None,
                "event_slug": None,
                "event_id": None,
                "parse_error": f"{type(exc).__name__}: {exc}",
            }

        return {
            "condition_id": condition_id,
            "yes_token_id": yes_token_id,
            "no_token_id": no_token_id,
            "tick_size": tick_size,
            "min_order_size": min_order_size,
            "neg_risk": neg_risk,
            "category": category,
            "tags": tags,
            "market_slug": market_slug,
            "event_title": event_title,
            "event_slug": event_slug,
            "event_id": event_id,
            "parse_error": None,
        }

    @staticmethod
    def _collect_text(raw_market: Mapping[str, Any], *keys: str) -> tuple[str, ...]:
        values: list[str] = []
        for key in keys:
            value = raw_market.get(key)
            if value is None:
                continue
            if isinstance(value, Mapping):
                values.extend(str(item) for item in value.values() if item is not None)
                continue
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value if item is not None)
                continue
            values.append(str(value))
        return tuple(values)

    @staticmethod
    def _first_value(raw_market: Mapping[str, Any], *keys: str) -> Any | None:
        for key in keys:
            if key in raw_market and raw_market[key] is not None:
                return raw_market[key]
        return None

    @staticmethod
    def _parse_decimal(value: Any | None) -> Decimal | None:
        if value is None or value == "":
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _parse_bool(value: Any | None) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        normalized = str(value).strip().lower()
        return normalized in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _parse_tags(value: Any | None) -> tuple[str, ...]:
        if value is None:
            return tuple()
        if isinstance(value, str):
            return tuple(tag.strip() for tag in value.split(",") if tag.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(tag).strip() for tag in value if str(tag).strip())
        return (str(value).strip(),)

    @classmethod
    def _contains_fdv(cls, text: str) -> bool:
        return any(pattern.search(text) for pattern in cls._FDV_PATTERNS)

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    @classmethod
    def _first_match(cls, text: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
        for pattern in patterns:
            match = pattern.search(text)
            if match is not None:
                return match.group(0)
        return None

    @staticmethod
    def _matched_signals(
        field_name: str,
        text: str,
        keywords: tuple[str, ...],
    ) -> tuple[MatchSignal, ...]:
        signals: list[MatchSignal] = []
        for keyword in keywords:
            if keyword in text:
                signals.append(MatchSignal(field_name=field_name, keyword=keyword))
        return tuple(signals)
