from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

from polymarket_trader.domain.events import DomainEvent, DomainEventType
from polymarket_trader.domain.market import Market, TradingStatus


class ClassificationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ClassificationRejectReason(StrEnum):
    MISSING_TRADING_CONDITIONS = "missing_trading_conditions"
    FIELD_PARSE_FAILED = "field_parse_failed"


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
    fees_enabled: bool | None
    maker_base_fee_bps: int | None
    taker_base_fee_bps: int | None
    category: str | None
    tags: tuple[str, ...]
    market_name: str | None
    market_question: str | None
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
            "fees_enabled": self.fees_enabled,
            "maker_base_fee_bps": self.maker_base_fee_bps,
            "taker_base_fee_bps": self.taker_base_fee_bps,
            "category": self.category,
            "tags": self.tags,
            "market_name": self.market_name,
            "market_question": self.market_question,
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
            market_name=self.market_name,
            market_question=self.market_question,
            event_id=self.event_id,
            event_title=self.event_title,
            event_slug=self.event_slug,
            tick_size=self.tick_size,
            min_order_size=self.min_order_size,
            neg_risk=self.neg_risk,
            fees_enabled=self.fees_enabled,
            maker_base_fee_bps=self.maker_base_fee_bps,
            taker_base_fee_bps=self.taker_base_fee_bps,
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
    """Parse raw market payloads into generic market candidates."""

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
            fees_enabled=parsed["fees_enabled"],
            maker_base_fee_bps=parsed["maker_base_fee_bps"],
            taker_base_fee_bps=parsed["taker_base_fee_bps"],
            category=parsed["category"],
            tags=parsed["tags"],
            market_name=parsed["market_name"],
            market_question=parsed["market_question"],
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
            fees_enabled=parsed["fees_enabled"],
            maker_base_fee_bps=parsed["maker_base_fee_bps"],
            taker_base_fee_bps=parsed["taker_base_fee_bps"],
            category=parsed["category"],
            tags=parsed["tags"],
            market_name=parsed["market_name"],
            market_question=parsed["market_question"],
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
            fee_schedule = self._as_mapping(self._first_value(raw_market, "fee_schedule", "feeSchedule"))
            fees_enabled = self._parse_nullable_bool(
                self._first_value(raw_market, "fees_enabled", "feesEnabled")
            )
            if fees_enabled is None and fee_schedule is not None:
                fees_enabled = self._parse_nullable_bool(
                    self._first_value(fee_schedule, "enabled", "feesEnabled")
                )
            maker_base_fee_bps = self._parse_int(
                self._first_value(
                    raw_market,
                    "maker_base_fee_bps",
                    "makerBaseFee",
                    "maker_base_fee",
                )
            )
            taker_base_fee_bps = self._parse_int(
                self._first_value(
                    raw_market,
                    "taker_base_fee_bps",
                    "takerBaseFee",
                    "taker_base_fee",
                )
            )
            if taker_base_fee_bps is None and fee_schedule is not None:
                taker_base_fee_bps = self._parse_int(
                    self._first_value(
                        fee_schedule,
                        "rate",
                        "base_fee",
                        "baseFee",
                    )
                )
            category = self._first_value(raw_market, "category")
            tags = self._parse_tags(self._first_value(raw_market, "tags"))
            market_name = self._first_value(raw_market, "name", "market_name", "marketName")
            market_question = self._first_value(
                raw_market,
                "question",
                "market_question",
                "prompt",
            )
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
                "fees_enabled": None,
                "maker_base_fee_bps": None,
                "taker_base_fee_bps": None,
                "category": None,
                "tags": tuple(),
                "market_name": None,
                "market_question": None,
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
            "fees_enabled": fees_enabled,
            "maker_base_fee_bps": maker_base_fee_bps,
            "taker_base_fee_bps": taker_base_fee_bps,
            "category": category,
            "tags": tags,
            "market_name": market_name,
            "market_question": market_question,
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
    def _parse_nullable_bool(value: Any | None) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if not normalized:
            return None
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
        return None

    @staticmethod
    def _parse_int(value: Any | None) -> int | None:
        if value is None or value == "":
            return None
        return int(Decimal(str(value)))

    @staticmethod
    def _as_mapping(value: Any | None) -> Mapping[str, Any] | None:
        if isinstance(value, Mapping):
            return value
        return None

    @staticmethod
    def _parse_tags(value: Any | None) -> tuple[str, ...]:
        if value is None:
            return tuple()
        if isinstance(value, str):
            return tuple(tag.strip() for tag in value.split(",") if tag.strip())
        if isinstance(value, (list, tuple, set)):
            return tuple(str(tag).strip() for tag in value if str(tag).strip())
        return (str(value).strip(),)

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
