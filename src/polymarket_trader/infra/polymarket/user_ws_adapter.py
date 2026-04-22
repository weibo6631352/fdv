from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from uuid import uuid4

from polymarket_trader.domain.order import Order, OrderSide, OrderStatus, OrderType


def first_value(mapping: Mapping[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def decimal_value(value: Any | None, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return default
    return Decimal(text)


def datetime_value(value: Any | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        numeric = None
    if numeric is not None:
        timestamp = float(numeric)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def text_value(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalized_status(value: Any | None) -> str:
    text = text_value(value)
    return "" if text is None else text.lower()


def normalize_order_status(value: Any | None) -> OrderStatus:
    text = normalized_status(value)
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


def normalize_order_type(value: Any | None, *, default: OrderType = OrderType.GTC) -> OrderType:
    text = normalized_status(value)
    if text == "fak":
        return OrderType.FAK
    if text == "gtc":
        return OrderType.GTC
    return default


def normalize_user_order_status(message: Mapping[str, Any]) -> OrderStatus:
    explicit = text_value(first_value(message, "status", "order_status", "orderStatus"))
    if explicit is not None:
        return normalize_order_status(explicit)
    event_kind = normalized_status(first_value(message, "type", "action"))
    matched = decimal_value(
        first_value(message, "filled_shares", "size_matched", "matched_amount"),
        default=Decimal("0"),
    ) or Decimal("0")
    original = decimal_value(first_value(message, "size_shares", "size", "original_size", "quantity"))
    if event_kind in {"cancellation", "cancel", "cancelled", "canceled"}:
        return OrderStatus.CANCELLED
    if original is not None and original > 0 and matched >= original:
        return OrderStatus.MATCHED
    if matched > 0:
        return OrderStatus.PARTIALLY_FILLED
    if event_kind in {"placement", "update"}:
        return OrderStatus.LIVE
    return OrderStatus.CREATED


def extract_condition_id(message: Mapping[str, Any]) -> str | None:
    return text_value(first_value(message, "condition_id", "conditionId", "condition", "market"))


def extract_token_id(message: Mapping[str, Any]) -> str | None:
    return text_value(first_value(message, "token_id", "tokenId", "asset_id", "assetId", "market_token_id"))


def extract_market_slug(message: Mapping[str, Any]) -> str | None:
    return text_value(first_value(message, "market_slug", "marketSlug", "slug"))


def extract_trace_id(message: Mapping[str, Any]) -> str:
    value = text_value(first_value(message, "trace_id", "traceId"))
    return value or uuid4().hex


def is_mapping_sequence(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, Mapping) for item in value)


def iter_order_snapshots(payload: Mapping[str, Any]) -> Iterable[Order]:
    candidates: Iterable[Any]
    if is_mapping_sequence(payload.get("orders")):
        candidates = payload["orders"]
    elif is_mapping_sequence(payload.get("open_orders")):
        candidates = payload["open_orders"]
    elif isinstance(payload.get("order"), Mapping):
        candidates = (payload["order"],)
    else:
        candidates = (payload,)

    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        condition_id = extract_condition_id(item)
        token_id = extract_token_id(item)
        if condition_id is None or token_id is None:
            continue
        order_type = normalize_order_type(item.get("order_type"), default=OrderType.GTC)
        side_text = normalized_status(item.get("side"))
        if side_text == "buy":
            side = OrderSide.BUY
        elif side_text == "sell":
            side = OrderSide.SELL
        elif item.get("amount_usdc") is not None or item.get("amount") is not None:
            side = OrderSide.BUY
        else:
            side = OrderSide.SELL
        price = decimal_value(item.get("price"), default=Decimal("0")) or Decimal("0")
        amount_usdc = decimal_value(item.get("amount_usdc") or item.get("amount"))
        size_shares = decimal_value(item.get("size_shares") or item.get("size") or item.get("original_size"))
        filled_shares = decimal_value(
            item.get("filled_shares") or item.get("size_matched") or item.get("matched_amount"),
            default=Decimal("0"),
        ) or Decimal("0")
        notional_usdc = decimal_value(item.get("notional_usdc"))
        if notional_usdc is None and price is not None and size_shares is not None:
            notional_usdc = price * size_shares
        remaining_shares = decimal_value(item.get("remaining_shares") or item.get("remaining_size"))
        if remaining_shares is None and size_shares is not None:
            remaining_shares = max(Decimal("0"), size_shares - filled_shares)
        yield Order(
            trace_id=extract_trace_id(item),
            condition_id=condition_id,
            token_id=token_id,
            market_slug=extract_market_slug(item),
            side=side,
            order_type=order_type,
            price=price,
            amount_usdc=amount_usdc,
            size_shares=size_shares,
            filled_shares=filled_shares,
            notional_usdc=notional_usdc,
            order_id=text_value(item.get("order_id") or item.get("id")),
            trade_id=text_value(item.get("trade_id")),
            status=normalize_user_order_status(item),
            idempotency_key=text_value(item.get("idempotency_key")),
            reason=text_value(item.get("reason")) or "",
            post_only=bool(item.get("post_only", False)),
            created_at=datetime_value(item.get("created_at") or item.get("timestamp")),
            updated_at=datetime_value(
                item.get("updated_at") or item.get("last_update") or item.get("timestamp")
            ),
            remaining_shares=remaining_shares,
        )
