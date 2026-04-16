from __future__ import annotations

import contextlib
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from json import loads
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from polymarket_trader.domain.events import Fill, sanitize_raw_response
from polymarket_trader.domain.market import Market, MarketOutcome, TradingStatus
from polymarket_trader.domain.order import (
    Order as OrderRecord,
    OrderSide,
    OrderStatus,
    OrderType,
)
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.domain.position import Position

_FEE_RATE_DENOMINATOR = Decimal("1000")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _first_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_value(payload: Mapping[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _maybe_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _iter_items(payload: Any, *keys: str) -> tuple[Any, ...]:
    if isinstance(payload, list):
        return tuple(payload)
    if isinstance(payload, Mapping):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return tuple(value)
    return ()


def _iter_mappings(payload: Any, *keys: str) -> tuple[Mapping[str, Any], ...]:
    items = _iter_items(payload, *keys)
    mappings: list[Mapping[str, Any]] = []
    for item in items:
        maybe = _maybe_mapping(item)
        if maybe is not None:
            mappings.append(maybe)
    return tuple(mappings)


def _normalize_http_proxy_url(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    scheme = urlparse(text).scheme.lower()
    if scheme not in {"http", "https"}:
        return None
    return text


def _resolve_proxy_url(base_url: str) -> str | None:
    scheme = urlparse(base_url).scheme.lower()
    candidates: list[str | None] = []
    if scheme == "https":
        candidates.extend((os.environ.get("HTTPS_PROXY"), os.environ.get("https_proxy")))
    if scheme in {"http", "https"}:
        candidates.extend((os.environ.get("HTTP_PROXY"), os.environ.get("http_proxy")))
    candidates.extend((os.environ.get("ALL_PROXY"), os.environ.get("all_proxy")))

    for candidate in candidates:
        normalized = _normalize_http_proxy_url(candidate)
        if normalized is not None:
            return normalized
    return None


def _unwrap_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    current: Mapping[str, Any] = payload
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        for key in ("data", "payload", "result", "order", "orderbook", "book"):
            value = current.get(key)
            if isinstance(value, Mapping):
                current = value
                break
        else:
            return current
    return payload


def _coerce_decimal(value: Any | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    with contextlib.suppress(InvalidOperation):
        return Decimal(text)
    return None


def _coerce_int(value: Any | None) -> int | None:
    number = _coerce_decimal(value)
    if number is None:
        return None
    with contextlib.suppress(ArithmeticError, ValueError):
        return int(number)
    return None


def _coerce_fee_rate_units(value: Any | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    numeric = _coerce_decimal(value)
    if numeric is None or numeric < Decimal("0"):
        return None
    if numeric < Decimal("1"):
        return int((numeric * _FEE_RATE_DENOMINATOR).to_integral_value())
    if numeric == numeric.to_integral_value():
        return int(numeric)
    return int((numeric * _FEE_RATE_DENOMINATOR).to_integral_value())


def _coerce_bool(value: Any | None) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "t", "yes", "y", "enabled", "active", "open"}:
        return True
    if text in {"0", "false", "f", "no", "n", "disabled", "closed"}:
        return False
    return None


def _coerce_datetime(value: Any | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        with contextlib.suppress(ValueError, OSError, OverflowError):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        with contextlib.suppress(ValueError, OSError, OverflowError):
            return datetime.fromtimestamp(float(text), tz=timezone.utc)
    with contextlib.suppress(ValueError):
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _summary(raw_response: Any | None, *, max_length: int = 512) -> str | None:
    return sanitize_raw_response(raw_response, max_length=max_length)


def _normalize_response_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping):
        for key in ("data", "events", "markets", "items", "results", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return payload
    return payload


def _string_tuple(value: Any | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Mapping):
        items: list[str] = []
        for key in ("label", "slug", "name"):
            text = _first_text(value, key)
            if text:
                items.append(text)
        return tuple(items)
    if isinstance(value, (list, tuple, set, frozenset)):
        items: list[str] = []
        for item in value:
            items.extend(_string_tuple(item))
        return tuple(items)
    text = str(value).strip()
    return (text,) if text else ()


def _token_id_tuple(value: Any | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        with contextlib.suppress(TypeError, ValueError):
            parsed = loads(text)
            return _token_id_tuple(parsed)
        return (text,)
    if isinstance(value, (list, tuple, set, frozenset)):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return tuple(items)
    text = str(value).strip()
    return (text,) if text else ()


def _market_outcomes(
    token_ids: tuple[str, ...],
    outcome_names: tuple[str, ...],
) -> tuple[MarketOutcome, ...]:
    if not token_ids:
        return ()
    resolved_names = list(outcome_names)
    if len(resolved_names) < len(token_ids):
        if not resolved_names and len(token_ids) == 2:
            resolved_names = ["YES", "NO"]
        while len(resolved_names) < len(token_ids):
            resolved_names.append(f"OUTCOME_{len(resolved_names)}")
    return tuple(
        MarketOutcome(token_id=token_id, outcome=resolved_names[index])
        for index, token_id in enumerate(token_ids)
    )


def _coerce_price_levels(value: Any) -> tuple[PriceLevel, ...]:
    if not isinstance(value, list):
        return ()
    levels: list[PriceLevel] = []
    for item in value:
        if isinstance(item, Mapping):
            price = _coerce_decimal(_first_value(item, "price", "p"))
            size = _coerce_decimal(_first_value(item, "size", "qty", "quantity", "amount"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            price = _coerce_decimal(item[0])
            size = _coerce_decimal(item[1])
        else:
            continue
        if price is None or size is None:
            continue
        levels.append(PriceLevel(price=price, size=size))
    return tuple(levels)


class PolymarketClientError(RuntimeError):
    """Polymarket 外部协议统一错误基类。

    交易主流程不该区分 HTTP、WS、解析或限速异常的细碎实现，因此这里统一收敛成结构化错误。
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str = "",
        url: str | None = None,
        status_code: int | None = None,
        code: str | None = None,
        retry_after_s: float | None = None,
        raw_response_summary: str | None = None,
        raw_response: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.url = url
        self.status_code = status_code
        self.code = code
        self.retry_after_s = retry_after_s
        self.raw_response_summary = raw_response_summary
        self.raw_response = raw_response

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "operation": self.operation,
            "url": self.url,
            "status_code": self.status_code,
            "code": self.code,
            "retry_after_s": self.retry_after_s,
            "raw_response_summary": self.raw_response_summary,
        }


class PolymarketTimeoutError(PolymarketClientError):
    """请求超时或 WS 连接超时。"""


class PolymarketAuthError(PolymarketClientError):
    """认证失败或凭据缺失。"""


class PolymarketRateLimitError(PolymarketClientError):
    """限速或临时封禁。"""


class PolymarketTransportError(PolymarketClientError):
    """网络、协议或上游 5xx 故障。"""


class PolymarketResponseError(PolymarketClientError):
    """响应可达但 payload 不符合协议。"""


class PolymarketWebSocketError(PolymarketClientError):
    """WebSocket 连接、订阅或消息解析失败。"""


def _normalize_client_error(
    exc: Exception,
    *,
    operation: str,
    url: str | None = None,
    raw_response: Any | None = None,
) -> PolymarketClientError:
    if isinstance(exc, PolymarketClientError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return PolymarketTimeoutError(
            f"{operation} timed out",
            operation=operation,
            url=url,
            raw_response_summary=_summary(raw_response),
            raw_response=raw_response,
        )
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        return _error_from_response(response, operation=operation)
    if isinstance(exc, httpx.HTTPError):
        return PolymarketTransportError(
            f"{operation} transport error: {exc}",
            operation=operation,
            url=url,
            raw_response_summary=_summary(raw_response),
            raw_response=raw_response,
        )
    return PolymarketResponseError(
        f"{operation} failed: {exc}",
        operation=operation,
        url=url,
        raw_response_summary=_summary(raw_response),
        raw_response=raw_response,
    )


def _error_from_response(
    response: httpx.Response,
    *,
    operation: str,
) -> PolymarketClientError:
    status_code = response.status_code
    retry_after_s: float | None = None
    with contextlib.suppress(Exception):
        header_value = response.headers.get("retry-after")
        if header_value:
            retry_after_s = float(header_value)

    detail: str | None = None
    code: str | None = None
    payload: Any | None = None
    with contextlib.suppress(Exception):
        payload = response.json()
        if isinstance(payload, Mapping):
            detail = _first_text(payload, "error", "message", "detail", "reason")
            code = _first_text(payload, "code", "error_code", "status")
        else:
            detail = str(payload)
    raw_summary = _summary(payload if payload is not None else response.text)
    message = detail or f"{operation} failed with HTTP {status_code}"
    if status_code in {401, 403}:
        return PolymarketAuthError(
            message,
            operation=operation,
            url=str(response.request.url),
            status_code=status_code,
            code=code,
            retry_after_s=retry_after_s,
            raw_response_summary=raw_summary,
            raw_response=payload,
        )
    if status_code == 429:
        return PolymarketRateLimitError(
            message,
            operation=operation,
            url=str(response.request.url),
            status_code=status_code,
            code=code,
            retry_after_s=retry_after_s,
            raw_response_summary=raw_summary,
            raw_response=payload,
        )
    if status_code >= 500:
        return PolymarketTransportError(
            message,
            operation=operation,
            url=str(response.request.url),
            status_code=status_code,
            code=code,
            retry_after_s=retry_after_s,
            raw_response_summary=raw_summary,
            raw_response=payload,
        )
    return PolymarketResponseError(
        message,
        operation=operation,
        url=str(response.request.url),
        status_code=status_code,
        code=code,
        retry_after_s=retry_after_s,
        raw_response_summary=raw_summary,
        raw_response=payload,
    )


class PolymarketRestClientBase:
    """可注入 `httpx.AsyncClient` 的轻量 REST 基类。

    这里不强行绑死认证实现。调用方可以注入已签名的 client，或先只消费公开市场接口。
    """

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 10.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        proxy = _resolve_proxy_url(self._base_url)
        client_kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "timeout": timeout_s,
            "headers": dict(headers or {}),
            "trust_env": False,
        }
        # 只接收 http/https 代理，避免把 socks 类型的 ALL_PROXY 直接交给 httpx 后导致启动异常。
        if proxy is not None:
            client_kwargs["proxy"] = proxy
        self._client = client or httpx.AsyncClient(**client_kwargs)

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "PolymarketRestClientBase":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        operation: str = "",
        unwrap: bool = True,
    ) -> Any:
        url = path if path.startswith("http") else f"{self._base_url}{path}"
        try:
            response = await self._client.request(
                method=method,
                url=path,
                params=params,
                json=json_body,
                headers=dict(headers or {}),
                timeout=timeout_s,
            )
            response.raise_for_status()
        except Exception as exc:
            raise _normalize_client_error(exc, operation=operation or f"{method} {path}", url=url) from exc

        if response.status_code == 204:
            return {}
        try:
            payload = response.json()
        except Exception as exc:
            raise PolymarketResponseError(
                f"{operation or method} returned non-JSON payload",
                operation=operation or f"{method} {path}",
                url=str(response.request.url),
                status_code=response.status_code,
                raw_response_summary=_summary(response.text),
                raw_response=response.text,
            ) from exc
        return _normalize_response_payload(payload) if unwrap else payload

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        operation: str = "",
        unwrap: bool = True,
    ) -> Any:
        return await self.request_json(
            "GET",
            path,
            params=params,
            headers=headers,
            timeout_s=timeout_s,
            operation=operation or f"GET {path}",
            unwrap=unwrap,
        )

    async def post_json(
        self,
        path: str,
        *,
        json_body: Any | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout_s: float | None = None,
        operation: str = "",
        unwrap: bool = True,
    ) -> Any:
        return await self.request_json(
            "POST",
            path,
            params=params,
            json_body=json_body,
            headers=headers,
            timeout_s=timeout_s,
            operation=operation or f"POST {path}",
            unwrap=unwrap,
        )


class PolymarketSubscriptionChannel(StrEnum):
    MARKET = "market"
    USER = "user"


@dataclass(frozen=True, slots=True)
class RawMarketEvent:
    source: str
    payload: Mapping[str, Any]
    trace_id: str = ""
    discovered_at: datetime = field(default_factory=_utc_now)
    condition_id: str | None = None
    market_slug: str | None = None
    dedupe_key: str | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", self.source.strip())

        trace_id = self.trace_id.strip() if self.trace_id else ""
        if not trace_id:
            trace_id = uuid4().hex
        object.__setattr__(self, "trace_id", trace_id)

        discovered_at = getattr(self, "discovered_at", None)
        if not isinstance(discovered_at, datetime):
            discovered_at = _utc_now()
        if discovered_at.tzinfo is None:
            discovered_at = discovered_at.replace(tzinfo=timezone.utc)
        object.__setattr__(self, "discovered_at", discovered_at)

        condition_id = self.condition_id or _first_text(
            self.payload,
            "condition_id",
            "conditionId",
            "condition",
        )
        market_slug = self.market_slug or _first_text(
            self.payload,
            "market_slug",
            "marketSlug",
            "slug",
        )
        object.__setattr__(self, "condition_id", condition_id)
        object.__setattr__(self, "market_slug", market_slug)

        dedupe_key = self.dedupe_key or condition_id or market_slug
        object.__setattr__(self, "dedupe_key", dedupe_key)

        summary = self.summary.strip() if self.summary else ""
        if not summary:
            summary = _summary(self.payload) or ""
        object.__setattr__(self, "summary", summary)

    @property
    def dedupe_identity(self) -> str | None:
        return self.dedupe_key or self.condition_id or self.market_slug

    @property
    def payload_preview(self) -> str:
        return self.summary


@dataclass(frozen=True, slots=True)
class ClobOrderRequest:
    token_id: str
    side: str
    order_type: str
    price: Decimal
    amount: Decimal
    post_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_id", str(self.token_id).strip())
        object.__setattr__(self, "side", str(self.side).strip().upper())
        object.__setattr__(self, "order_type", str(self.order_type).strip().upper())
        object.__setattr__(self, "price", _coerce_decimal(self.price) or Decimal("0"))
        object.__setattr__(self, "amount", _coerce_decimal(self.amount) or Decimal("0"))
        object.__setattr__(self, "post_only", bool(self.post_only))

    def to_payload(self) -> dict[str, Any]:
        # BUY 的 amount 语义是花费的 USDC.e 金额；SELL 的 amount 语义是 shares。
        return {
            "token_id": self.token_id,
            "side": self.side,
            "order_type": self.order_type,
            "price": str(self.price),
            "amount": str(self.amount),
            "post_only": self.post_only,
        }


@dataclass(frozen=True, slots=True)
class GammaMarketDTO:
    raw: Mapping[str, Any]
    condition_id: str | None = None
    market_slug: str | None = None
    question: str | None = None
    title: str | None = None
    event_id: str | None = None
    event_title: str | None = None
    event_slug: str | None = None
    icon_url: str | None = None
    end_date: datetime | None = None
    outcomes: tuple[MarketOutcome, ...] = field(default_factory=tuple)
    tick_size: Decimal | None = None
    min_order_size: Decimal | None = None
    neg_risk: bool = False
    fees_enabled: bool | None = None
    maker_base_fee_bps: int | None = None
    taker_base_fee_bps: int | None = None
    category: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    clob_enabled: bool | None = None
    raw_summary: str = ""

    def __post_init__(self) -> None:
        event = next(iter(_iter_mappings(self.raw, "events")), None)
        fee_schedule = _maybe_mapping(_first_value(self.raw, "fee_schedule", "feeSchedule"))
        token_ids = _token_id_tuple(_first_value(self.raw, "clobTokenIds"))
        outcome_names = _string_tuple(_first_value(self.raw, "outcomes"))
        raw_fees_enabled = _first_value(self.raw, "fees_enabled", "feesEnabled")
        fee_schedule_rate_bps = (
            _coerce_fee_rate_units(_first_value(fee_schedule, "rate", "base_fee", "baseFee"))
            if fee_schedule is not None
            else None
        )
        raw_taker_base_fee = _first_value(
            self.raw,
            "taker_base_fee_bps",
            "takerBaseFee",
            "taker_base_fee",
        )
        raw_tags = _first_value(self.raw, "tags")
        if raw_tags is None and event is not None:
            raw_tags = _first_value(event, "tags")
        object.__setattr__(self, "condition_id", self.condition_id or _first_text(self.raw, "condition_id", "conditionId", "condition"))
        object.__setattr__(self, "market_slug", self.market_slug or _first_text(self.raw, "market_slug", "marketSlug", "slug"))
        object.__setattr__(self, "question", self.question or _first_text(self.raw, "question", "prompt", "market_question"))
        object.__setattr__(self, "title", self.title or _first_text(self.raw, "title", "name"))
        object.__setattr__(self, "event_id", self.event_id or _first_text(self.raw, "event_id", "eventId", "id") or _first_text(event or {}, "id"))
        object.__setattr__(self, "event_title", self.event_title or _first_text(self.raw, "event_title", "eventTitle") or _first_text(event or {}, "title", "name"))
        object.__setattr__(self, "event_slug", self.event_slug or _first_text(self.raw, "event_slug", "eventSlug") or _first_text(event or {}, "slug"))
        object.__setattr__(self, "icon_url", self.icon_url or _first_text(self.raw, "icon") or _first_text(event or {}, "icon"))
        object.__setattr__(
            self,
            "end_date",
            self.end_date
            if self.end_date is not None
            else _coerce_datetime(
                _first_value(self.raw, "endDate", "end_date")
                or _first_value(event or {}, "endDate", "end_date")
            ),
        )
        object.__setattr__(
            self,
            "outcomes",
            self.outcomes or _market_outcomes(token_ids, outcome_names),
        )
        object.__setattr__(self, "tick_size", self.tick_size if self.tick_size is not None else _coerce_decimal(_first_value(self.raw, "orderPriceMinTickSize", "tick_size", "tickSize")))
        object.__setattr__(self, "min_order_size", self.min_order_size if self.min_order_size is not None else _coerce_decimal(_first_value(self.raw, "orderMinSize", "min_order_size", "minOrderSize")))
        object.__setattr__(self, "neg_risk", self.neg_risk or bool(_coerce_bool(_first_value(self.raw, "neg_risk", "negRisk"))))
        object.__setattr__(
            self,
            "fees_enabled",
            self.fees_enabled
            if self.fees_enabled is not None
            else (
                _coerce_bool(raw_fees_enabled)
                if raw_fees_enabled is not None
                else (
                    None
                    if fee_schedule is None
                    else _coerce_bool(_first_value(fee_schedule, "enabled", "feesEnabled"))
                )
            ),
        )
        object.__setattr__(
            self,
            "maker_base_fee_bps",
            self.maker_base_fee_bps
            if self.maker_base_fee_bps is not None
            else _coerce_int(_first_value(self.raw, "maker_base_fee_bps", "makerBaseFee", "maker_base_fee")),
        )
        object.__setattr__(
            self,
            "taker_base_fee_bps",
            self.taker_base_fee_bps
            if self.taker_base_fee_bps is not None
            else (
                fee_schedule_rate_bps
                if fee_schedule_rate_bps is not None
                else _coerce_int(raw_taker_base_fee)
            ),
        )
        object.__setattr__(self, "category", self.category or _first_text(self.raw, "category", "cat") or _first_text(event or {}, "category"))
        object.__setattr__(self, "tags", self.tags or _string_tuple(raw_tags))
        object.__setattr__(self, "active", self.active if self.active is not None else _coerce_bool(_first_value(self.raw, "active", "is_active")))
        object.__setattr__(self, "closed", self.closed if self.closed is not None else _coerce_bool(_first_value(self.raw, "closed", "is_closed")))
        object.__setattr__(self, "archived", self.archived if self.archived is not None else _coerce_bool(_first_value(self.raw, "archived", "is_archived")))
        object.__setattr__(self, "clob_enabled", self.clob_enabled if self.clob_enabled is not None else _coerce_bool(_first_value(self.raw, "clob_enabled", "enableOrderBook", "clobEnabled")))
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)

    def to_market(self) -> Market:
        if self.condition_id is None or self.market_slug is None or not self.outcomes:
            raise ValueError("gamma market payload missing required market identifiers")
        tick_size = self.tick_size or Decimal("0.01")
        min_order_size = self.min_order_size or Decimal("1")
        status = TradingStatus.ELIGIBLE
        if self.closed:
            status = TradingStatus.CLOSED
        elif self.archived:
            status = TradingStatus.PAUSED
        return Market(
            condition_id=self.condition_id,
            market_slug=self.market_slug,
            outcomes=self.outcomes,
            market_name=self.title,
            market_question=self.question,
            event_id=self.event_id,
            event_title=self.event_title,
            event_slug=self.event_slug,
            icon_url=self.icon_url,
            end_date=self.end_date,
            tick_size=tick_size,
            min_order_size=min_order_size,
            neg_risk=self.neg_risk,
            fees_enabled=self.fees_enabled,
            maker_base_fee_bps=self.maker_base_fee_bps,
            taker_base_fee_bps=self.taker_base_fee_bps,
            fee_rate_bps=self.taker_base_fee_bps,
            category=self.category,
            tags=self.tags,
            trading_status=status,
        )

    def to_raw_market_event(self, *, source: str, trace_id: str | None = None) -> RawMarketEvent:
        return RawMarketEvent(
            source=source,
            payload=self.raw,
            trace_id=trace_id or "",
            condition_id=self.condition_id,
            market_slug=self.market_slug,
            summary=self.raw_summary,
        )


@dataclass(frozen=True, slots=True)
class GammaEventDTO:
    raw: Mapping[str, Any]
    event_id: str | None = None
    event_slug: str | None = None
    event_title: str | None = None
    category: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    markets: tuple[GammaMarketDTO, ...] = field(default_factory=tuple)
    active: bool | None = None
    closed: bool | None = None
    raw_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", self.event_id or _first_text(self.raw, "event_id", "eventId", "id"))
        object.__setattr__(self, "event_slug", self.event_slug or _first_text(self.raw, "event_slug", "eventSlug", "slug"))
        object.__setattr__(self, "event_title", self.event_title or _first_text(self.raw, "event_title", "title", "name"))
        object.__setattr__(self, "category", self.category or _first_text(self.raw, "category"))
        object.__setattr__(self, "tags", self.tags or _string_tuple(_first_value(self.raw, "tags")))
        object.__setattr__(self, "active", self.active if self.active is not None else _coerce_bool(_first_value(self.raw, "active", "is_active")))
        object.__setattr__(self, "closed", self.closed if self.closed is not None else _coerce_bool(_first_value(self.raw, "closed", "is_closed")))
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)

    def iter_markets(self) -> tuple[GammaMarketDTO, ...]:
        if self.markets:
            return self.markets
        markets = []
        for item in _iter_mappings(self.raw, "markets", "items", "results"):
            markets.append(normalize_gamma_market(item))
        return tuple(markets)

    def to_raw_market_events(self, *, source: str, trace_id: str | None = None) -> tuple[RawMarketEvent, ...]:
        markets = self.iter_markets()
        if not markets:
            return (
                RawMarketEvent(
                    source=source,
                    payload=self.raw,
                    trace_id=trace_id or "",
                    condition_id=_first_text(self.raw, "condition_id", "conditionId", "condition"),
                    market_slug=_first_text(self.raw, "market_slug", "marketSlug", "slug"),
                    summary=self.raw_summary,
                ),
            )
        raw_tags = _first_value(self.raw, "tags")
        raw_category = _first_value(self.raw, "category")
        raw_events: list[RawMarketEvent] = []
        for market in markets:
            payload = dict(market.raw)
            if _first_value(payload, "eventId") is None and self.event_id is not None:
                payload["eventId"] = self.event_id
            if _first_value(payload, "eventSlug") is None and self.event_slug is not None:
                payload["eventSlug"] = self.event_slug
            if _first_value(payload, "eventTitle") is None and self.event_title is not None:
                payload["eventTitle"] = self.event_title
            if _first_value(payload, "tags") is None and raw_tags is not None:
                payload["tags"] = raw_tags
            if _first_value(payload, "category") is None and raw_category is not None:
                payload["category"] = raw_category
            raw_events.append(
                RawMarketEvent(
                    source=source,
                    payload=payload,
                    trace_id=trace_id or "",
                    condition_id=market.condition_id,
                    market_slug=market.market_slug,
                    summary=market.raw_summary,
                )
            )
        return tuple(raw_events)


@dataclass(frozen=True, slots=True)
class OrderbookLevelDTO:
    price: Decimal
    size: Decimal

    def to_price_level(self) -> PriceLevel:
        return PriceLevel(price=self.price, size=self.size)


@dataclass(frozen=True, slots=True)
class ClobOrderbookDTO:
    raw: Mapping[str, Any]
    token_id: str
    bids: tuple[OrderbookLevelDTO, ...] = field(default_factory=tuple)
    asks: tuple[OrderbookLevelDTO, ...] = field(default_factory=tuple)
    best_bid: Decimal | None = None
    best_ask: Decimal | None = None
    best_bid_size: Decimal | None = None
    best_ask_size: Decimal | None = None
    last_trade_price: Decimal | None = None
    tick_size: Decimal | None = None
    min_order_size: Decimal | None = None
    market_slug: str | None = None
    condition_id: str | None = None
    received_at: datetime = field(default_factory=_utc_now)
    raw_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_id", str(self.token_id).strip())
        object.__setattr__(self, "market_slug", self.market_slug or _first_text(self.raw, "market_slug", "marketSlug", "slug"))
        object.__setattr__(self, "condition_id", self.condition_id or _first_text(self.raw, "condition_id", "conditionId", "condition"))
        object.__setattr__(self, "best_bid", self.best_bid if self.best_bid is not None else _coerce_decimal(_first_value(self.raw, "best_bid", "bestBid")))
        object.__setattr__(self, "best_ask", self.best_ask if self.best_ask is not None else _coerce_decimal(_first_value(self.raw, "best_ask", "bestAsk")))
        object.__setattr__(self, "best_bid_size", self.best_bid_size if self.best_bid_size is not None else _coerce_decimal(_first_value(self.raw, "best_bid_size", "bestBidSize")))
        object.__setattr__(self, "best_ask_size", self.best_ask_size if self.best_ask_size is not None else _coerce_decimal(_first_value(self.raw, "best_ask_size", "bestAskSize")))
        object.__setattr__(self, "last_trade_price", self.last_trade_price if self.last_trade_price is not None else _coerce_decimal(_first_value(self.raw, "last_trade_price", "lastTradePrice")))
        object.__setattr__(self, "tick_size", self.tick_size if self.tick_size is not None else _coerce_decimal(_first_value(self.raw, "tick_size", "tickSize")))
        object.__setattr__(self, "min_order_size", self.min_order_size if self.min_order_size is not None else _coerce_decimal(_first_value(self.raw, "min_order_size", "minOrderSize")))
        received_at = _coerce_datetime(_first_value(self.raw, "received_at", "receivedAt", "timestamp", "ts"))
        if received_at is not None:
            object.__setattr__(self, "received_at", received_at)
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def to_snapshot(self) -> OrderbookSnapshot:
        return OrderbookSnapshot(
            token_id=self.token_id,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            bids=tuple(level.to_price_level() for level in self.bids),
            asks=tuple(level.to_price_level() for level in self.asks),
            received_at=self.received_at,
            market_slug=self.market_slug,
            condition_id=self.condition_id,
            best_bid_size=self.best_bid_size,
            best_ask_size=self.best_ask_size,
            last_trade_price=self.last_trade_price,
            tick_size=self.tick_size,
        )


@dataclass(frozen=True, slots=True)
class ClobPriceHistoryPointDTO:
    raw: Mapping[str, Any]
    timestamp: datetime = field(default_factory=_utc_now)
    price: Decimal | None = None

    def __post_init__(self) -> None:
        timestamp = _coerce_datetime(_first_value(self.raw, "t", "timestamp", "ts"))
        if timestamp is not None:
            object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "price", self.price if self.price is not None else _coerce_decimal(_first_value(self.raw, "p", "price")))


@dataclass(frozen=True, slots=True)
class ClobPriceHistoryDTO:
    raw: Mapping[str, Any]
    history: tuple[ClobPriceHistoryPointDTO, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.history:
            points = tuple(
                ClobPriceHistoryPointDTO(raw=item)
                for item in _iter_mappings(self.raw, "history", "items", "results")
            )
            object.__setattr__(self, "history", points)


@dataclass(frozen=True, slots=True)
class ClobOrderDTO:
    raw: Mapping[str, Any]
    token_id: str
    side: OrderSide
    order_type: OrderType
    price: Decimal
    order_id: str | None = None
    market_slug: str | None = None
    condition_id: str | None = None
    amount_usdc: Decimal | None = None
    size_shares: Decimal | None = None
    filled_shares: Decimal = Decimal("0")
    remaining_shares: Decimal | None = None
    trade_id: str | None = None
    status: str = "created"
    reason: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    raw_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_id", str(self.token_id).strip())
        object.__setattr__(self, "order_id", self.order_id or _first_text(self.raw, "order_id", "orderId", "id"))
        object.__setattr__(self, "market_slug", self.market_slug or _first_text(self.raw, "market_slug", "marketSlug", "slug"))
        object.__setattr__(
            self,
            "condition_id",
            self.condition_id or _first_text(self.raw, "condition_id", "conditionId", "condition", "market"),
        )
        object.__setattr__(self, "amount_usdc", self.amount_usdc if self.amount_usdc is not None else _coerce_decimal(_first_value(self.raw, "amount_usdc", "amount")))
        object.__setattr__(
            self,
            "size_shares",
            self.size_shares
            if self.size_shares is not None
            else _coerce_decimal(_first_value(self.raw, "size_shares", "size", "quantity", "original_size")),
        )
        object.__setattr__(
            self,
            "filled_shares",
            self.filled_shares
            if self.filled_shares is not None
            else _coerce_decimal(_first_value(self.raw, "filled_shares", "filledSize", "size_matched")) or Decimal("0"),
        )
        remaining_shares = self.remaining_shares
        if remaining_shares is None:
            remaining_shares = _coerce_decimal(_first_value(self.raw, "remaining_shares", "remainingSize"))
        if remaining_shares is None and self.size_shares is not None:
            remaining_shares = max(self.size_shares - self.filled_shares, Decimal("0"))
        object.__setattr__(self, "remaining_shares", remaining_shares)
        object.__setattr__(self, "trade_id", self.trade_id or _first_text(self.raw, "trade_id", "tradeId"))
        object.__setattr__(
            self,
            "status",
            self.status or _normalize_order_status_text(_first_text(self.raw, "status")) or "created",
        )
        object.__setattr__(self, "reason", self.reason or _first_text(self.raw, "reason", "message") or "")
        created_at = _coerce_datetime(_first_value(self.raw, "created_at", "createdAt", "timestamp"))
        if created_at is not None:
            object.__setattr__(self, "created_at", created_at)
        updated_at = _coerce_datetime(_first_value(self.raw, "updated_at", "updatedAt", "last_update", "lastUpdate"))
        if updated_at is not None:
            object.__setattr__(self, "updated_at", updated_at)
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)

    def to_order_record(self) -> OrderRecord:
        return OrderRecord(
            trace_id=_first_text(self.raw, "trace_id", "traceId") or "",
            condition_id=self.condition_id or "",
            token_id=self.token_id,
            market_slug=self.market_slug,
            side=self.side,
            order_type=self.order_type,
            price=self.price,
            amount_usdc=self.amount_usdc,
            size_shares=self.size_shares,
            filled_shares=self.filled_shares,
            remaining_shares=self.remaining_shares,
            trade_id=self.trade_id,
            order_id=self.order_id,
            status=_coerce_order_status(self.status),
            reason=self.reason,
            post_only=bool(_coerce_bool(_first_value(self.raw, "post_only", "postOnly"))),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True, slots=True)
class ClobFillDTO:
    raw: Mapping[str, Any]
    token_id: str
    side: OrderSide
    price: Decimal
    size_shares: Decimal
    order_id: str | None = None
    trade_id: str | None = None
    condition_id: str | None = None
    market_slug: str | None = None
    notional_usdc: Decimal | None = None
    status: str = "confirmed"
    confirmed_at: datetime = field(default_factory=_utc_now)
    raw_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "token_id", str(self.token_id).strip())
        order_id = self.order_id or _first_text(self.raw, "order_id", "orderId", "taker_order_id", "takerOrderId")
        if order_id is None:
            maker_orders = _first_value(self.raw, "maker_orders", "makerOrders")
            if isinstance(maker_orders, list) and maker_orders:
                first_order = maker_orders[0]
                if isinstance(first_order, Mapping):
                    order_id = _first_text(first_order, "order_id", "orderId", "id")
                else:
                    text = str(first_order).strip()
                    order_id = text or None
        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(self, "trade_id", self.trade_id or _first_text(self.raw, "trade_id", "tradeId", "id"))
        object.__setattr__(
            self,
            "condition_id",
            self.condition_id or _first_text(self.raw, "condition_id", "conditionId", "condition", "market"),
        )
        object.__setattr__(self, "market_slug", self.market_slug or _first_text(self.raw, "market_slug", "marketSlug", "slug"))
        object.__setattr__(self, "notional_usdc", self.notional_usdc if self.notional_usdc is not None else _coerce_decimal(_first_value(self.raw, "notional_usdc", "notional", "spent_usdc", "spentUsdC")))
        object.__setattr__(
            self,
            "status",
            self.status or _normalize_trade_status_text(_first_text(self.raw, "status")) or "confirmed",
        )
        confirmed_at = _coerce_datetime(
            _first_value(self.raw, "confirmed_at", "confirmedAt", "timestamp", "match_time", "matchTime", "last_update", "lastUpdate")
        )
        if confirmed_at is not None:
            object.__setattr__(self, "confirmed_at", confirmed_at)
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)

    def to_fill(self) -> Fill:
        return Fill(
            trace_id=_first_text(self.raw, "trace_id", "traceId") or "",
            order_id=self.order_id,
            trade_id=self.trade_id,
            condition_id=self.condition_id,
            token_id=self.token_id,
            market_slug=self.market_slug,
            side=self.side.value,
            price=self.price,
            size=self.size_shares,
            notional_usdc=self.notional_usdc or self.price * self.size_shares,
            status=self.status,
            confirmed_at=self.confirmed_at,
        )


@dataclass(frozen=True, slots=True)
class BalanceAllowanceDTO:
    raw: Mapping[str, Any]
    balance_usdc: Decimal = Decimal("0")
    allowance_usdc: Decimal = Decimal("0")
    updated_at: datetime = field(default_factory=_utc_now)
    raw_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "balance_usdc",
            self.balance_usdc
            if self.balance_usdc is not None
            else _coerce_decimal(_first_value(self.raw, "balance")) or Decimal("0"),
        )
        object.__setattr__(
            self,
            "allowance_usdc",
            self.allowance_usdc
            if self.allowance_usdc is not None
            else _coerce_decimal(_first_value(self.raw, "allowance")) or Decimal("0"),
        )
        updated_at = _coerce_datetime(_first_value(self.raw, "updated_at", "updatedAt", "timestamp"))
        if updated_at is not None:
            object.__setattr__(self, "updated_at", updated_at)
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)


@dataclass(frozen=True, slots=True)
class DataPositionDTO:
    raw: Mapping[str, Any]
    condition_id: str
    token_id: str
    shares: Decimal
    cost_usdc: Decimal
    market_slug: str | None = None
    proxy_wallet: str | None = None
    open_buy_shares: Decimal = Decimal("0")
    open_sell_shares: Decimal = Decimal("0")
    pending_buy_shares: Decimal = Decimal("0")
    confirmed_shares: Decimal = Decimal("0")
    last_order_id: str | None = None
    last_trade_id: str | None = None
    confirmation_status: str = "unknown"
    updated_at: datetime = field(default_factory=_utc_now)
    avg_price: Decimal | None = None
    initial_value: Decimal | None = None
    current_value: Decimal | None = None
    cash_pnl: Decimal | None = None
    percent_pnl: Decimal | None = None
    total_bought: Decimal | None = None
    realized_pnl: Decimal | None = None
    percent_realized_pnl: Decimal | None = None
    cur_price: Decimal | None = None
    redeemable: bool | None = None
    mergeable: bool | None = None
    title: str | None = None
    icon: str | None = None
    event_slug: str | None = None
    outcome: str | None = None
    outcome_index: int | None = None
    opposite_outcome: str | None = None
    opposite_asset: str | None = None
    end_date: datetime | None = None
    negative_risk: bool | None = None
    raw_summary: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition_id", str(self.condition_id).strip())
        object.__setattr__(self, "token_id", str(self.token_id).strip())
        object.__setattr__(self, "market_slug", self.market_slug or _first_text(self.raw, "market_slug", "marketSlug", "slug"))
        object.__setattr__(self, "proxy_wallet", self.proxy_wallet or _first_text(self.raw, "proxyWallet", "proxy_wallet"))
        object.__setattr__(self, "shares", self.shares if self.shares is not None else _coerce_decimal(_first_value(self.raw, "shares", "size", "quantity")) or Decimal("0"))
        cost_usdc = self.cost_usdc
        if cost_usdc is None:
            cost_usdc = _coerce_decimal(_first_value(self.raw, "cost_usdc", "cost", "value", "initialValue"))
        if cost_usdc is None:
            avg_price = _coerce_decimal(_first_value(self.raw, "avg_price", "avgPrice"))
            if avg_price is not None:
                cost_usdc = avg_price * self.shares
        object.__setattr__(self, "cost_usdc", cost_usdc or Decimal("0"))
        object.__setattr__(self, "open_buy_shares", self.open_buy_shares if self.open_buy_shares is not None else _coerce_decimal(_first_value(self.raw, "open_buy_shares", "openBuyShares")) or Decimal("0"))
        object.__setattr__(self, "open_sell_shares", self.open_sell_shares if self.open_sell_shares is not None else _coerce_decimal(_first_value(self.raw, "open_sell_shares", "openSellShares")) or Decimal("0"))
        object.__setattr__(self, "pending_buy_shares", self.pending_buy_shares if self.pending_buy_shares is not None else _coerce_decimal(_first_value(self.raw, "pending_buy_shares", "pendingBuyShares")) or Decimal("0"))
        object.__setattr__(self, "confirmed_shares", self.confirmed_shares if self.confirmed_shares is not None else _coerce_decimal(_first_value(self.raw, "confirmed_shares", "confirmedShares")) or Decimal("0"))
        object.__setattr__(self, "last_order_id", self.last_order_id or _first_text(self.raw, "last_order_id", "lastOrderId"))
        object.__setattr__(self, "last_trade_id", self.last_trade_id or _first_text(self.raw, "last_trade_id", "lastTradeId"))
        object.__setattr__(self, "confirmation_status", self.confirmation_status or _first_text(self.raw, "confirmation_status", "confirmationStatus") or "unknown")
        updated_at = _coerce_datetime(_first_value(self.raw, "updated_at", "updatedAt", "timestamp"))
        if updated_at is not None:
            object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "avg_price", self.avg_price if self.avg_price is not None else _coerce_decimal(_first_value(self.raw, "avg_price", "avgPrice")))
        object.__setattr__(self, "initial_value", self.initial_value if self.initial_value is not None else _coerce_decimal(_first_value(self.raw, "initialValue", "initial_value")))
        object.__setattr__(self, "current_value", self.current_value if self.current_value is not None else _coerce_decimal(_first_value(self.raw, "currentValue", "current_value")))
        object.__setattr__(self, "cash_pnl", self.cash_pnl if self.cash_pnl is not None else _coerce_decimal(_first_value(self.raw, "cashPnl", "cash_pnl")))
        object.__setattr__(self, "percent_pnl", self.percent_pnl if self.percent_pnl is not None else _coerce_decimal(_first_value(self.raw, "percentPnl", "percent_pnl")))
        object.__setattr__(self, "total_bought", self.total_bought if self.total_bought is not None else _coerce_decimal(_first_value(self.raw, "totalBought", "total_bought")))
        object.__setattr__(self, "realized_pnl", self.realized_pnl if self.realized_pnl is not None else _coerce_decimal(_first_value(self.raw, "realizedPnl", "realized_pnl")))
        object.__setattr__(
            self,
            "percent_realized_pnl",
            self.percent_realized_pnl
            if self.percent_realized_pnl is not None
            else _coerce_decimal(_first_value(self.raw, "percentRealizedPnl", "percent_realized_pnl")),
        )
        object.__setattr__(self, "cur_price", self.cur_price if self.cur_price is not None else _coerce_decimal(_first_value(self.raw, "curPrice", "cur_price")))
        object.__setattr__(self, "redeemable", self.redeemable if self.redeemable is not None else _coerce_bool(_first_value(self.raw, "redeemable")))
        object.__setattr__(self, "mergeable", self.mergeable if self.mergeable is not None else _coerce_bool(_first_value(self.raw, "mergeable")))
        object.__setattr__(self, "title", self.title or _first_text(self.raw, "title"))
        object.__setattr__(self, "icon", self.icon or _first_text(self.raw, "icon"))
        object.__setattr__(self, "event_slug", self.event_slug or _first_text(self.raw, "eventSlug", "event_slug"))
        object.__setattr__(self, "outcome", self.outcome or _first_text(self.raw, "outcome"))
        object.__setattr__(
            self,
            "outcome_index",
            self.outcome_index
            if self.outcome_index is not None
            else _coerce_int(_first_value(self.raw, "outcomeIndex", "outcome_index")),
        )
        object.__setattr__(self, "opposite_outcome", self.opposite_outcome or _first_text(self.raw, "oppositeOutcome", "opposite_outcome"))
        object.__setattr__(self, "opposite_asset", self.opposite_asset or _first_text(self.raw, "oppositeAsset", "opposite_asset"))
        object.__setattr__(
            self,
            "end_date",
            self.end_date if self.end_date is not None else _coerce_datetime(_first_value(self.raw, "endDate", "end_date")),
        )
        object.__setattr__(
            self,
            "negative_risk",
            self.negative_risk
            if self.negative_risk is not None
            else _coerce_bool(_first_value(self.raw, "negativeRisk", "negative_risk")),
        )
        summary = self.raw_summary.strip() if self.raw_summary else ""
        if not summary:
            summary = _summary(self.raw) or ""
        object.__setattr__(self, "raw_summary", summary)

    def to_position(self) -> Position:
        return Position(
            condition_id=self.condition_id,
            token_id=self.token_id,
            shares=self.shares,
            cost_usdc=self.cost_usdc,
            market_slug=self.market_slug,
            open_buy_shares=self.open_buy_shares,
            open_sell_shares=self.open_sell_shares,
            pending_buy_shares=self.pending_buy_shares,
            confirmed_shares=self.confirmed_shares,
            last_order_id=self.last_order_id,
            last_trade_id=self.last_trade_id,
            confirmation_status=self.confirmation_status,
            updated_at=self.updated_at,
        )
@dataclass(frozen=True, slots=True)
class WebSocketSubscription:
    channel: PolymarketSubscriptionChannel
    token_ids: tuple[str, ...] = field(default_factory=tuple)
    condition_ids: tuple[str, ...] = field(default_factory=tuple)
    custom_feature_enabled: bool = False
    auth: Mapping[str, str] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = {"type": self.channel.value}
        if self.channel is PolymarketSubscriptionChannel.MARKET:
            payload["assets_ids"] = list(self.token_ids)
            # Market Channel 的 best_bid_ask / new_market / market_resolved 只有开启 custom feature 才会送。
            payload["custom_feature_enabled"] = True if self.custom_feature_enabled else False
        else:
            payload["markets"] = list(self.condition_ids)
            if self.auth is not None:
                payload["auth"] = {str(key): str(value) for key, value in self.auth.items()}
        payload.update(dict(self.raw))
        return payload


@dataclass(frozen=True, slots=True)
class WebSocketMessage:
    channel: str
    message_type: str
    payload: Mapping[str, Any]
    raw: Mapping[str, Any]
    trace_id: str = ""
    token_id: str | None = None
    condition_id: str | None = None
    market_slug: str | None = None
    sequence: int | None = None
    received_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "channel", self.channel.strip())
        object.__setattr__(self, "message_type", self.message_type.strip().lower())
        object.__setattr__(self, "trace_id", self.trace_id.strip() if self.trace_id else uuid4().hex)
        object.__setattr__(
            self,
            "token_id",
            self.token_id
            or _first_text(self.raw, "token_id", "tokenId", "asset_id", "assetId", "winning_asset_id"),
        )
        object.__setattr__(
            self,
            "condition_id",
            self.condition_id or _first_text(self.raw, "condition_id", "conditionId", "condition", "market"),
        )
        object.__setattr__(self, "market_slug", self.market_slug or _first_text(self.raw, "market_slug", "marketSlug", "slug"))
        if self.sequence is None:
            with contextlib.suppress(Exception):
                sequence = _first_value(self.raw, "sequence", "seq", "version")
                object.__setattr__(self, "sequence", None if sequence is None else int(sequence))

    @property
    def event_type(self) -> str:
        return self.message_type


def normalize_gamma_market(payload: Mapping[str, Any]) -> GammaMarketDTO:
    return GammaMarketDTO(raw=_unwrap_mapping(payload))


def normalize_gamma_event(payload: Mapping[str, Any]) -> GammaEventDTO:
    normalized = _unwrap_mapping(payload)
    markets = tuple(normalize_gamma_market(item) for item in _iter_mappings(normalized, "markets", "items", "results"))
    return GammaEventDTO(raw=normalized, markets=markets)


def gamma_event_to_raw_market_events(
    payload: Mapping[str, Any],
    *,
    source: str,
    trace_id: str | None = None,
) -> tuple[RawMarketEvent, ...]:
    return normalize_gamma_event(payload).to_raw_market_events(source=source, trace_id=trace_id)


def normalize_orderbook_payload(
    payload: Mapping[str, Any],
    *,
    token_id: str,
    market_slug: str | None = None,
    condition_id: str | None = None,
) -> ClobOrderbookDTO:
    normalized = _unwrap_mapping(payload)
    bids = _coerce_price_levels(_first_value(normalized, "bids", "buy"))
    asks = _coerce_price_levels(_first_value(normalized, "asks", "sell"))
    best_bid = _coerce_decimal(_first_value(normalized, "best_bid", "bestBid"))
    best_ask = _coerce_decimal(_first_value(normalized, "best_ask", "bestAsk"))
    if best_bid is None and bids:
        best_bid = max(level.price for level in bids)
    if best_ask is None and asks:
        best_ask = min(level.price for level in asks)
    best_bid_size = _coerce_decimal(_first_value(normalized, "best_bid_size", "bestBidSize"))
    best_ask_size = _coerce_decimal(_first_value(normalized, "best_ask_size", "bestAskSize"))
    if best_bid_size is None and bids:
        best_bid_size = max((level.size for level in bids if level.price == best_bid), default=None)
    if best_ask_size is None and asks:
        best_ask_size = min((level.size for level in asks if level.price == best_ask), default=None)
    last_trade_price = _coerce_decimal(_first_value(normalized, "last_trade_price", "lastTradePrice"))
    tick_size = _coerce_decimal(_first_value(normalized, "tick_size", "tickSize"))
    min_order_size = _coerce_decimal(_first_value(normalized, "min_order_size", "minOrderSize"))
    received_at = _coerce_datetime(_first_value(normalized, "received_at", "receivedAt", "timestamp", "ts"))
    return ClobOrderbookDTO(
        raw=normalized,
        token_id=token_id,
        bids=tuple(OrderbookLevelDTO(level.price, level.size) for level in bids),
        asks=tuple(OrderbookLevelDTO(level.price, level.size) for level in asks),
        best_bid=best_bid,
        best_ask=best_ask,
        best_bid_size=best_bid_size,
        best_ask_size=best_ask_size,
        last_trade_price=last_trade_price,
        tick_size=tick_size,
        min_order_size=min_order_size,
        market_slug=market_slug,
        condition_id=condition_id,
        received_at=received_at or _utc_now(),
    )


def normalize_price_history_payload(payload: Mapping[str, Any]) -> ClobPriceHistoryDTO:
    normalized = _unwrap_mapping(payload)
    return ClobPriceHistoryDTO(raw=normalized)


def orderbook_payload_to_snapshot(
    payload: Mapping[str, Any],
    *,
    token_id: str,
    market_slug: str | None = None,
    condition_id: str | None = None,
) -> OrderbookSnapshot:
    return normalize_orderbook_payload(
        payload,
        token_id=token_id,
        market_slug=market_slug,
        condition_id=condition_id,
    ).to_snapshot()


def normalize_order_payload(payload: Mapping[str, Any]) -> ClobOrderDTO:
    normalized = _unwrap_mapping(payload)
    side = _first_text(normalized, "side") or OrderSide.BUY.value
    order_type = _first_text(normalized, "order_type", "orderType") or OrderType.GTC.value
    return ClobOrderDTO(
        raw=normalized,
        token_id=_first_text(normalized, "token_id", "tokenId", "asset_id", "assetId") or "",
        side=OrderSide(side.upper()),
        order_type=OrderType(order_type.upper()),
        price=_coerce_decimal(_first_value(normalized, "price")) or Decimal("0"),
        order_id=_first_text(normalized, "order_id", "orderId", "id"),
        market_slug=_first_text(normalized, "market_slug", "marketSlug", "slug"),
        condition_id=_first_text(normalized, "condition_id", "conditionId", "condition", "market"),
        amount_usdc=_coerce_decimal(_first_value(normalized, "amount_usdc", "amount")),
        size_shares=_coerce_decimal(_first_value(normalized, "size_shares", "size", "quantity", "original_size")),
        filled_shares=_coerce_decimal(_first_value(normalized, "filled_shares", "filledSize", "size_matched")) or Decimal("0"),
        remaining_shares=_coerce_decimal(_first_value(normalized, "remaining_shares", "remainingSize")),
        trade_id=_first_text(normalized, "trade_id", "tradeId"),
        status=_normalize_order_status_text(_first_text(normalized, "status")) or "created",
        reason=_first_text(normalized, "reason", "message") or "",
        created_at=_coerce_datetime(_first_value(normalized, "created_at", "createdAt")) or _utc_now(),
        updated_at=_coerce_datetime(_first_value(normalized, "updated_at", "updatedAt", "last_update", "lastUpdate")) or _utc_now(),
    )


def normalize_fill_payload(payload: Mapping[str, Any]) -> ClobFillDTO:
    normalized = _unwrap_mapping(payload)
    side_text = _first_text(normalized, "side") or OrderSide.BUY.value
    return ClobFillDTO(
        raw=normalized,
        token_id=_first_text(normalized, "token_id", "tokenId", "asset_id", "assetId") or "",
        side=OrderSide(side_text.upper()),
        price=_coerce_decimal(_first_value(normalized, "price", "trade_price", "tradePrice")) or Decimal("0"),
        size_shares=_coerce_decimal(_first_value(normalized, "size_shares", "size", "quantity")) or Decimal("0"),
        order_id=_first_text(normalized, "order_id", "orderId", "taker_order_id", "takerOrderId"),
        trade_id=_first_text(normalized, "trade_id", "tradeId", "id"),
        condition_id=_first_text(normalized, "condition_id", "conditionId", "condition", "market"),
        market_slug=_first_text(normalized, "market_slug", "marketSlug", "slug"),
        notional_usdc=_coerce_decimal(_first_value(normalized, "notional_usdc", "notional", "value")),
        status=_normalize_trade_status_text(_first_text(normalized, "status")) or "confirmed",
        confirmed_at=_coerce_datetime(_first_value(normalized, "confirmed_at", "confirmedAt", "match_time", "matchTime", "last_update", "lastUpdate")) or _utc_now(),
    )


def normalize_position_payload(payload: Mapping[str, Any]) -> DataPositionDTO:
    normalized = _unwrap_mapping(payload)
    shares = _coerce_decimal(_first_value(normalized, "shares", "size", "quantity")) or Decimal("0")
    cost_usdc = _coerce_decimal(_first_value(normalized, "cost_usdc", "cost", "value", "initialValue"))
    if cost_usdc is None:
        avg_price = _coerce_decimal(_first_value(normalized, "avg_price", "avgPrice"))
        if avg_price is not None:
            cost_usdc = avg_price * shares
    return DataPositionDTO(
        raw=normalized,
        condition_id=_first_text(normalized, "condition_id", "conditionId", "condition") or "",
        token_id=_first_text(normalized, "token_id", "tokenId", "asset_id", "assetId", "asset") or "",
        shares=shares,
        cost_usdc=cost_usdc or Decimal("0"),
        market_slug=_first_text(normalized, "market_slug", "marketSlug", "slug"),
        open_buy_shares=_coerce_decimal(_first_value(normalized, "open_buy_shares", "openBuyShares")) or Decimal("0"),
        open_sell_shares=_coerce_decimal(_first_value(normalized, "open_sell_shares", "openSellShares")) or Decimal("0"),
        pending_buy_shares=_coerce_decimal(_first_value(normalized, "pending_buy_shares", "pendingBuyShares")) or Decimal("0"),
        confirmed_shares=_coerce_decimal(_first_value(normalized, "confirmed_shares", "confirmedShares")) or Decimal("0"),
        last_order_id=_first_text(normalized, "last_order_id", "lastOrderId"),
        last_trade_id=_first_text(normalized, "last_trade_id", "lastTradeId"),
        confirmation_status=_first_text(normalized, "confirmation_status", "confirmationStatus") or "unknown",
        updated_at=_coerce_datetime(_first_value(normalized, "updated_at", "updatedAt")) or _utc_now(),
    )


def normalize_balance_allowance_payload(payload: Mapping[str, Any]) -> BalanceAllowanceDTO:
    normalized = _unwrap_mapping(payload)
    balance = _coerce_decimal(_first_value(normalized, "balance"))
    allowance = _coerce_decimal(_first_value(normalized, "allowance"))
    return BalanceAllowanceDTO(
        raw=normalized,
        balance_usdc=balance or Decimal("0"),
        allowance_usdc=allowance or Decimal("0"),
        updated_at=_coerce_datetime(_first_value(normalized, "updated_at", "updatedAt")) or _utc_now(),
    )


def data_position_to_domain_position(payload: Mapping[str, Any]) -> Position:
    return normalize_position_payload(payload).to_position()


def orderbook_to_domain_snapshot(payload: Mapping[str, Any], *, token_id: str) -> OrderbookSnapshot:
    return normalize_orderbook_payload(payload, token_id=token_id).to_snapshot()


def build_market_subscription_request(token_ids: Iterable[str]) -> dict[str, Any]:
    # Market Channel 的 `best_bid_ask` / `new_market` / `market_resolved` 需要 `custom_feature_enabled: true`。
    return WebSocketSubscription(
        channel=PolymarketSubscriptionChannel.MARKET,
        token_ids=tuple(str(token_id).strip() for token_id in token_ids if str(token_id).strip()),
        custom_feature_enabled=True,
    ).to_payload()


def build_user_subscription_request(
    condition_ids: Iterable[str],
    *,
    auth: Mapping[str, str],
) -> dict[str, Any]:
    return WebSocketSubscription(
        channel=PolymarketSubscriptionChannel.USER,
        condition_ids=tuple(
            str(condition_id).strip() for condition_id in condition_ids if str(condition_id).strip()
        ),
        auth=auth,
    ).to_payload()


def parse_ws_message(
    payload: Any,
    *,
    channel_hint: str | None = None,
) -> WebSocketMessage:
    messages = parse_ws_messages(payload, channel_hint=channel_hint)
    if len(messages) != 1:
        raise PolymarketWebSocketError(
            "websocket frame contains multiple messages",
            operation="parse_ws_message",
            raw_response_summary=_summary(payload),
            raw_response=payload,
        )
    return messages[0]


def parse_ws_messages(
    payload: Any,
    *,
    channel_hint: str | None = None,
) -> tuple[WebSocketMessage, ...]:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        payload = loads(payload)
    if isinstance(payload, list):
        messages: list[WebSocketMessage] = []
        for item in payload:
            if not isinstance(item, Mapping):
                raise PolymarketWebSocketError(
                    "websocket message is not a mapping",
                    operation="parse_ws_messages",
                    raw_response_summary=_summary(item),
                    raw_response=item,
                )
            messages.append(_parse_ws_mapping(item, channel_hint=channel_hint))
        return tuple(messages)
    if not isinstance(payload, Mapping):
        raise PolymarketWebSocketError(
            "websocket message is not a mapping",
            operation="parse_ws_messages",
            raw_response_summary=_summary(payload),
            raw_response=payload,
        )
    return (_parse_ws_mapping(payload, channel_hint=channel_hint),)


def _parse_ws_mapping(
    payload: Mapping[str, Any],
    *,
    channel_hint: str | None = None,
) -> WebSocketMessage:
    message_type = _infer_ws_message_type(payload)
    channel = channel_hint or _first_text(payload, "channel", "channel_type") or "market"

    nested_payload = _first_value(payload, "payload", "data", "message")
    if isinstance(nested_payload, Mapping):
        structured_payload = nested_payload
    else:
        structured_payload = payload

    sequence = _first_value(payload, "sequence", "seq", "version")
    sequence_value: int | None = None
    with contextlib.suppress(TypeError, ValueError):
        if sequence is not None:
            sequence_value = int(sequence)
    return WebSocketMessage(
        channel=channel,
        message_type=message_type,
        payload=structured_payload,
        raw=payload,
        token_id=_first_text(
            payload,
            "token_id",
            "tokenId",
            "asset_id",
            "assetId",
            "winning_asset_id",
        ),
        condition_id=_first_text(payload, "condition_id", "conditionId", "condition", "market"),
        market_slug=_first_text(payload, "market_slug", "marketSlug", "slug"),
        sequence=sequence_value,
    )


def _infer_ws_message_type(payload: Mapping[str, Any]) -> str:
    explicit = _first_text(
        payload,
        "event_type",
        "message_type",
        "channel_event",
        "event",
        "type",
        "action",
    )
    if explicit is not None:
        return explicit
    if isinstance(payload.get("price_changes"), list):
        return "price_change"
    if isinstance(payload.get("bids"), list) or isinstance(payload.get("asks"), list):
        return "book"
    if _first_value(payload, "best_bid", "bestBid", "best_ask", "bestAsk", "bid", "ask") is not None:
        return "best_bid_ask"
    return "message"


def _coerce_order_status(value: str) -> OrderStatus:
    text = value.strip().lower()
    if text in {"created", "new"}:
        return OrderStatus.CREATED
    if text in {"signed", "signing"}:
        return OrderStatus.SIGNED
    if text in {"submitted", "open"}:
        return OrderStatus.SUBMITTED
    if text in {"cancel_requested", "cancel-requested"}:
        return OrderStatus.CANCEL_REQUESTED
    if text in {"matched", "match"}:
        return OrderStatus.MATCHED
    if text in {"partially_filled", "partial_fill", "partial-filled"}:
        return OrderStatus.PARTIALLY_FILLED
    if text in {"no_fill", "no-fill", "unfilled"}:
        return OrderStatus.NO_FILL
    if text in {"live", "resting", "open_live"}:
        return OrderStatus.LIVE
    if text in {"cancelled", "canceled"}:
        return OrderStatus.CANCELLED
    if text in {"rejected", "reject"}:
        return OrderStatus.REJECTED
    if text in {"failed", "error"}:
        return OrderStatus.FAILED
    return OrderStatus.CREATED


def _normalize_order_status_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("order_status_"):
        text = text.removeprefix("order_status_")
    aliases = {
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "delayed": "submitted",
        "open": "submitted",
        "unmatched": "no_fill",
        "live": "live",
        "matched": "matched",
        "partially_filled": "partially_filled",
        "partial_filled": "partially_filled",
        "rejected": "rejected",
        "failed": "failed",
    }
    return aliases.get(text, text)


def _normalize_trade_status_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().lower()
    if not text:
        return None
    if text.startswith("trade_status_"):
        text = text.removeprefix("trade_status_")
    aliases = {
        "confirmed": "confirmed",
        "matched": "matched",
        "mined": "mined",
        "retrying": "retrying",
        "failed": "failed",
    }
    return aliases.get(text, text)


__all__ = [
    "BalanceAllowanceDTO",
    "ClobFillDTO",
    "ClobOrderDTO",
    "ClobOrderRequest",
    "ClobOrderbookDTO",
    "ClobPriceHistoryDTO",
    "ClobPriceHistoryPointDTO",
    "DataPositionDTO",
    "GammaEventDTO",
    "GammaMarketDTO",
    "OrderbookLevelDTO",
    "PolymarketAuthError",
    "PolymarketClientError",
    "PolymarketRateLimitError",
    "PolymarketResponseError",
    "PolymarketRestClientBase",
    "PolymarketSubscriptionChannel",
    "PolymarketTimeoutError",
    "PolymarketTransportError",
    "PolymarketWebSocketError",
    "RawMarketEvent",
    "WebSocketMessage",
    "WebSocketSubscription",
    "build_market_subscription_request",
    "build_user_subscription_request",
    "data_position_to_domain_position",
    "gamma_event_to_raw_market_events",
    "normalize_balance_allowance_payload",
    "normalize_fill_payload",
    "normalize_gamma_event",
    "normalize_gamma_market",
    "normalize_order_payload",
    "normalize_orderbook_payload",
    "normalize_price_history_payload",
    "normalize_position_payload",
    "orderbook_payload_to_snapshot",
    "orderbook_to_domain_snapshot",
    "parse_ws_message",
]
