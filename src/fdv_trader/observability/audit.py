from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from fdv_trader.domain.events import DomainEventType

MAX_RAW_RESPONSE_LENGTH = 4096


_SENSITIVE_KEY_SUFFIXES = (
    "_secret",
    "_password",
    "_token",
    "_signature",
    "_cookie",
)
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "mnemonic",
    "passphrase",
    "password",
    "private_key",
    "seed",
    "seed_phrase",
    "secret",
    "session_token",
    "access_token",
    "refresh_token",
    "signature",
    "token",
}
_KV_REDACT_PATTERN = re.compile(
    r"(?i)\b("
    r"api[_-]?key|apikey|authorization|bearer|cookie|mnemonic|passphrase|password|"
    r"private[_-]?key|seed(?:[_-]?phrase)?|secret|session[_-]?token|access[_-]?token|"
    r"refresh[_-]?token|signature|token"
    r")\b(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_REDACT_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+=/]+")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime | None) -> datetime:
    return value if value is not None else _now_utc()


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _SENSITIVE_KEYS:
        return True
    return any(normalized.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _truncate_text(text: str) -> str:
    if len(text) <= MAX_RAW_RESPONSE_LENGTH:
        return text
    return f"{text[:MAX_RAW_RESPONSE_LENGTH]}...<truncated>"


def _redact_text(text: str) -> str:
    redacted = _KV_REDACT_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    redacted = _BEARER_REDACT_PATTERN.sub("Bearer [REDACTED]", redacted)
    return _truncate_text(redacted)


def _sanitize_structure(value: Any, *, _depth: int = 0) -> Any:
    if value is None:
        return None
    if _depth > 8:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = _sanitize_structure(item, _depth=_depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_structure(item, _depth=_depth + 1) for item in value]
    if isinstance(value, bytes):
        return _redact_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return _redact_text(value)
        return _sanitize_structure(parsed, _depth=_depth + 1)
    if isinstance(value, (int, float, bool)):
        return value
    return _redact_text(str(value))


def sanitize_raw_response(raw_response: Any | None) -> str | None:
    """清洗原始响应，限制长度并去掉密钥、签名和凭证类字段。"""
    if raw_response is None:
        return None
    sanitized = _sanitize_structure(raw_response)
    if sanitized is None:
        return None
    if isinstance(sanitized, str):
        return sanitized
    try:
        text = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
    except TypeError:
        text = str(sanitized)
    return _truncate_text(text)


def _immutable_payload(payload: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not payload:
        return MappingProxyType({})
    return MappingProxyType(_sanitize_structure(dict(payload)))


@dataclass(frozen=True, slots=True, init=False)
class AuditEvent:
    trace_id: str
    event_id: str
    event_title: str
    market_slug: str | None = None
    condition_id: str | None = None
    token_id: str | None = None
    outcome: str | None = None
    side: str | None = None
    order_type: str | None = None
    price: Any | None = None
    size: Any | None = None
    notional_usdc: Any | None = None
    order_id: str | None = None
    trade_id: str | None = None
    tx_hash: str | None = None
    status: str | None = None
    reason: str | None = None
    raw_response: str | None = None
    created_at: datetime = field(default_factory=_now_utc)
    updated_at: datetime = field(default_factory=_now_utc)
    payload: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __init__(
        self,
        event_type: str | None = None,
        trace_id: str | None = None,
        created_at: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> None:
        merged: dict[str, Any] = {}
        if payload:
            merged.update(dict(payload))
        merged.update(fields)

        event_title = merged.pop("event_title", None) or event_type or merged.pop("event_type", None)
        if event_title is None:
            raise ValueError("AuditEvent requires event_type/event_title")
        if trace_id is None:
            trace_id = merged.pop("trace_id", None)
        if trace_id is None:
            raise ValueError("AuditEvent requires trace_id")

        created_at = _normalize_datetime(created_at or merged.pop("created_at", None))
        updated_at = merged.pop("updated_at", None) or created_at
        updated_at = _normalize_datetime(updated_at)
        if updated_at < created_at:
            updated_at = created_at

        raw_response = merged.pop("raw_response", None)
        if raw_response is None and payload is not None:
            raw_response = dict(payload).get("raw_response")

        payload_data = dict(payload) if payload else {}
        payload_data.update(merged)

        event_fields = {
            "trace_id": trace_id,
            "event_id": merged.pop("event_id", None) or uuid4().hex,
            "event_title": str(event_title),
            "market_slug": merged.pop("market_slug", None),
            "condition_id": merged.pop("condition_id", None),
            "token_id": merged.pop("token_id", None),
            "outcome": merged.pop("outcome", None),
            "side": merged.pop("side", None),
            "order_type": merged.pop("order_type", None),
            "price": merged.pop("price", None),
            "size": merged.pop("size", None),
            "notional_usdc": merged.pop("notional_usdc", None),
            "order_id": merged.pop("order_id", None),
            "trade_id": merged.pop("trade_id", None),
            "tx_hash": merged.pop("tx_hash", None),
            "status": merged.pop("status", None),
            "reason": merged.pop("reason", None),
            # raw response 要限长、脱敏，避免把签名、凭证和大块返回体原样打进审计库。
            "raw_response": sanitize_raw_response(raw_response),
            "created_at": created_at,
            "updated_at": updated_at,
            # 交易动作先写 outbox，再由异步 worker 落库；这里保留归一化后的 payload 便于转交。
            "payload": _immutable_payload(payload_data),
        }

        for key, value in event_fields.items():
            object.__setattr__(self, key, value)

    @property
    def event_type(self) -> str:
        return self.event_title

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "event_id": self.event_id,
            "event_title": self.event_title,
            "market_slug": self.market_slug,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "outcome": self.outcome,
            "side": self.side,
            "order_type": self.order_type,
            "price": self.price,
            "size": self.size,
            "notional_usdc": self.notional_usdc,
            "order_id": self.order_id,
            "trade_id": self.trade_id,
            "tx_hash": self.tx_hash,
            "status": self.status,
            "reason": self.reason,
            "raw_response": self.raw_response,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.payload)
        payload.update(self.to_dict())
        return payload

    def with_trace_id(self, trace_id: str) -> "AuditEvent":
        return AuditEvent(**{**self.to_payload(), "trace_id": trace_id})

    def with_updated_at(self, updated_at: datetime | None = None) -> "AuditEvent":
        return AuditEvent(**{**self.to_payload(), "updated_at": _normalize_datetime(updated_at)})

    def with_raw_response(self, raw_response: Any | None) -> "AuditEvent":
        return AuditEvent(**{**self.to_payload(), "raw_response": raw_response})
