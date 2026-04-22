from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Any, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from polymarket_trader.domain.allocation import Allocation
from polymarket_trader.domain.events import AuditEvent, Fill, OutboxEvent
from polymarket_trader.domain.market import Market, MarketOutcome, TradingStatus
from polymarket_trader.domain.order import Order, OrderSide, OrderStatus, OrderType
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.domain.position import Position
from polymarket_trader.infra.db.repositories import (
    AccountSnapshotRepository,
    AllocationRepository,
    AuditEventRepository,
    FillRepository,
    MarketRepository,
    OrderRepository,
    OrderbookSnapshotRepository,
    OutboxEventRepository,
    PositionRepository,
)
from polymarket_trader.runtime.account_state import AccountSnapshot

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decimal(value: Any | None, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return default


def _int(value: Any | None, default: int | None = None) -> int | None:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        try:
            return int(Decimal(text))
        except (InvalidOperation, ValueError):
            return default


def _bool(value: Any | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "open", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "closed", "disabled"}:
        return False
    return default


def _datetime(value: Any | None, default: datetime | None = None) -> datetime | None:
    if value is None:
        return default
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return default
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return default
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fee_rate_units_from_market_payload(payload: Mapping[str, Any] | None) -> int | None:
    if not isinstance(payload, Mapping):
        return None
    fee_schedule = payload.get("feeSchedule")
    if not isinstance(fee_schedule, Mapping):
        fee_schedule = payload.get("fee_schedule")
    if not isinstance(fee_schedule, Mapping):
        return None
    rate = fee_schedule.get("rate")
    if rate is None:
        rate = fee_schedule.get("base_fee")
    if rate is None:
        rate = fee_schedule.get("baseFee")
    if rate is None or isinstance(rate, bool):
        return None
    numeric = _decimal(rate)
    if numeric is None or numeric < Decimal("0"):
        return None
    if numeric < Decimal("1"):
        return int((numeric * Decimal("1000")).to_integral_value())
    if numeric == numeric.to_integral_value():
        return int(numeric)
    return int((numeric * Decimal("1000")).to_integral_value())


def _string_tuple(value: Any | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        items = []
        for item in value:
            text = _text(item)
            if text:
                items.append(text)
        return tuple(items)
    text = _text(value)
    return () if text is None else (text,)


def _mapping(value: Any | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _pair_tuple(value: Any | None) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    pairs: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            first = _text(item[0])
            second = _text(item[1]) or ""
            if first is not None:
                pairs.append((first, second))
    return tuple(pairs)


def _price_levels(value: Any | None) -> tuple[PriceLevel, ...]:
    if not isinstance(value, list):
        return ()
    levels: list[PriceLevel] = []
    for item in value:
        if isinstance(item, Mapping):
            price = _decimal(item.get("price"))
            size = _decimal(item.get("size"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            price = _decimal(item[0])
            size = _decimal(item[1])
        else:
            continue
        if price is None or size is None:
            continue
        levels.append(PriceLevel(price=price, size=size))
    return tuple(levels)


def _trading_status(value: Any | None) -> TradingStatus:
    text = (_text(value) or TradingStatus.CANDIDATE.value).lower()
    try:
        return TradingStatus(text)
    except ValueError:
        return TradingStatus.CANDIDATE


def _order_side(value: Any | None) -> OrderSide | None:
    text = (_text(value) or "").upper()
    try:
        return OrderSide(text)
    except ValueError:
        return None


def _order_type(value: Any | None) -> OrderType | None:
    text = (_text(value) or "").upper()
    try:
        return OrderType(text)
    except ValueError:
        return None


def _order_status(value: Any | None) -> OrderStatus:
    text = (_text(value) or "").lower()
    mapping = {
        "created": OrderStatus.CREATED,
        "signed": OrderStatus.SIGNED,
        "submitted": OrderStatus.SUBMITTED,
        "cancel_requested": OrderStatus.CANCEL_REQUESTED,
        "matched": OrderStatus.MATCHED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "partial_fill": OrderStatus.PARTIALLY_FILLED,
        "no_fill": OrderStatus.NO_FILL,
        "live": OrderStatus.LIVE,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
        "failed": OrderStatus.FAILED,
        "full_fill": OrderStatus.MATCHED,
        "unknown_timeout": OrderStatus.FAILED,
        "timeout": OrderStatus.FAILED,
    }
    return mapping.get(text, OrderStatus.FAILED)


def _log_skip(kind: str, record: Mapping[str, Any], reason: str) -> None:
    logger.debug(
        "skip persistence record because required fields are missing",
        extra={
            "kind": kind,
            "reason": reason,
            "trace_id": _text(record.get("trace_id")),
            "event_id": _text(record.get("event_id")),
        },
    )


def _audit_event_from_record(record: Mapping[str, Any]) -> AuditEvent | None:
    trace_id = _text(record.get("trace_id"))
    event_title = _text(record.get("event_title"))
    if trace_id is None or event_title is None:
        _log_skip("audit", record, "missing trace_id or event_title")
        return None
    created_at = _datetime(record.get("created_at"), _utc_now())
    payload = dict(record)
    payload["created_at"] = created_at
    payload["updated_at"] = _datetime(record.get("updated_at"), created_at) or created_at
    return AuditEvent(
        event_title=event_title,
        trace_id=trace_id,
        created_at=created_at,
        payload=payload,
    )


def _market_from_record(record: Mapping[str, Any]) -> Market | None:
    condition_id = _text(record.get("condition_id"))
    market_slug = _text(record.get("market_slug"))
    raw_market = record.get("raw_payload")
    if not isinstance(raw_market, Mapping):
        raw_market = record.get("market_data")
    if not isinstance(raw_market, Mapping):
        raw_market = {}
    outcomes = _market_outcomes(
        record.get("outcomes") or raw_market.get("outcomes"),
        record.get("token_ids") or raw_market.get("token_ids"),
    )
    if condition_id is None or market_slug is None or not outcomes:
        _log_skip("market", record, "missing condition_id/market_slug/outcomes")
        return None
    schedule_fee_rate_bps = _fee_rate_units_from_market_payload(raw_market)
    return Market(
        condition_id=condition_id,
        market_slug=market_slug,
        outcomes=outcomes,
        event_id=_text(record.get("event_id")) or _text(record.get("source_event_id")),
        event_title=_text(record.get("event_title")),
        event_slug=_text(record.get("event_slug")),
        icon_url=_text(record.get("icon_url")) or _text(raw_market.get("icon_url")) or _text(raw_market.get("icon")),
        end_date=(
            _datetime(record.get("end_date"))
            or _datetime(raw_market.get("end_date"))
            or _datetime(raw_market.get("endDate"))
        ),
        tick_size=_decimal(record.get("tick_size"), Decimal("0.01")) or Decimal("0.01"),
        min_order_size=_decimal(record.get("min_order_size"), Decimal("1")) or Decimal("1"),
        neg_risk=_bool(record.get("neg_risk")),
        fees_enabled=None if record.get("fees_enabled") is None else _bool(record.get("fees_enabled")),
        maker_base_fee_bps=_int(record.get("maker_base_fee_bps")),
        taker_base_fee_bps=(
            schedule_fee_rate_bps
            if schedule_fee_rate_bps is not None
            else _int(record.get("taker_base_fee_bps"))
        ),
        fee_rate_bps=(
            schedule_fee_rate_bps
            if schedule_fee_rate_bps is not None
            else _int(record.get("fee_rate_bps"))
        ),
        fee_rate_updated_at=(
            None
            if schedule_fee_rate_bps is not None
            else _datetime(record.get("fee_rate_updated_at"))
        ),
        category=_text(record.get("category")),
        tags=_string_tuple(record.get("tags")),
        matched_keywords=_string_tuple(record.get("matched_keywords")),
        trading_status=_trading_status(record.get("trading_status")),
        reject_reason=(
            _text(record.get("reject_reason"))
            or _text(record.get("parse_reason"))
            or _text(record.get("classification_reason"))
        ),
    )


def _market_outcomes(
    outcome_records: Any | None,
    token_ids_value: Any | None,
) -> tuple[MarketOutcome, ...]:
    outcomes: list[MarketOutcome] = []
    if isinstance(outcome_records, Sequence) and not isinstance(outcome_records, (str, bytes, bytearray)):
        for item in outcome_records:
            if not isinstance(item, Mapping):
                continue
            token_id = _text(item.get("token_id"))
            outcome = _text(item.get("outcome"))
            if token_id is None or outcome is None:
                continue
            outcomes.append(MarketOutcome(token_id=token_id, outcome=outcome))
    if outcomes:
        return tuple(outcomes)
    token_ids = _string_tuple(token_ids_value)
    if not token_ids:
        return tuple()
    outcome_names = ("YES", "NO") if len(token_ids) == 2 else tuple(
        f"OUTCOME_{index}" for index in range(len(token_ids))
    )
    return tuple(
        MarketOutcome(token_id=token_id, outcome=outcome_names[index])
        for index, token_id in enumerate(token_ids)
    )


def _orderbook_from_record(record: Mapping[str, Any]) -> OrderbookSnapshot | None:
    token_id = _text(record.get("token_id"))
    if token_id is None:
        _log_skip("orderbook", record, "missing token_id")
        return None
    return OrderbookSnapshot(
        token_id=token_id,
        best_bid=_decimal(record.get("best_bid")),
        best_ask=_decimal(record.get("best_ask")),
        bids=_price_levels(record.get("bids")),
        asks=_price_levels(record.get("asks")),
        received_at=_datetime(
            record.get("received_at") or record.get("snapshot_time") or record.get("created_at"),
            _utc_now(),
        )
        or _utc_now(),
        market_slug=_text(record.get("market_slug")),
        condition_id=_text(record.get("condition_id")),
        best_bid_size=_decimal(record.get("best_bid_size")),
        best_ask_size=_decimal(record.get("best_ask_size")),
        last_trade_price=_decimal(record.get("last_trade_price")),
        tick_size=_decimal(record.get("tick_size")),
    )


def _order_from_record(record: Mapping[str, Any]) -> Order | None:
    condition_id = _text(record.get("condition_id"))
    token_id = _text(record.get("token_id"))
    side = _order_side(record.get("side"))
    order_type = _order_type(record.get("order_type"))
    price = _decimal(record.get("price"))
    if condition_id is None or token_id is None or side is None or order_type is None or price is None:
        _log_skip("order", record, "missing condition_id/token_id/side/order_type/price")
        return None
    return Order(
        trace_id=_text(record.get("trace_id")) or "",
        condition_id=condition_id,
        token_id=token_id,
        market_slug=_text(record.get("market_slug")),
        side=side,
        order_type=order_type,
        price=price,
        amount_usdc=_decimal(record.get("amount_usdc")),
        size_shares=_decimal(record.get("size_shares")),
        filled_shares=_decimal(record.get("filled_shares"), Decimal("0")) or Decimal("0"),
        remaining_shares=_decimal(record.get("remaining_shares")),
        notional_usdc=_decimal(record.get("notional_usdc")),
        order_id=_text(record.get("order_id")),
        trade_id=_text(record.get("trade_id")),
        status=_order_status(record.get("status")),
        idempotency_key=_text(record.get("idempotency_key")),
        reason=_text(record.get("reason")) or "",
        post_only=_bool(record.get("post_only")),
        created_at=_datetime(record.get("created_at")),
        updated_at=_datetime(record.get("updated_at") or record.get("created_at")),
    )


def _fill_from_record(record: Mapping[str, Any]) -> Fill | None:
    trace_id = _text(record.get("trace_id"))
    if trace_id is None:
        _log_skip("fill", record, "missing trace_id")
        return None
    return Fill(
        trace_id=trace_id,
        event_type=_text(record.get("event_type")) or "fill_recorded",
        event_id=_text(record.get("event_id")) or "",
        market_slug=_text(record.get("market_slug")),
        condition_id=_text(record.get("condition_id")),
        token_id=_text(record.get("token_id")),
        created_at=_datetime(record.get("created_at"), _utc_now()) or _utc_now(),
        order_id=_text(record.get("order_id")),
        trade_id=_text(record.get("trade_id")),
        side=_text(record.get("side")),
        price=_decimal(record.get("price")),
        size=_decimal(record.get("size")) or _decimal(record.get("filled_shares")),
        notional_usdc=_decimal(record.get("notional_usdc")),
        status=_text(record.get("status")) or "confirmed",
        confirmed_at=_datetime(record.get("confirmed_at") or record.get("created_at")),
    )


def _position_from_record(record: Mapping[str, Any]) -> Position | None:
    condition_id = _text(record.get("condition_id"))
    token_id = _text(record.get("token_id"))
    if condition_id is None or token_id is None:
        _log_skip("position", record, "missing condition_id/token_id")
        return None
    return Position(
        condition_id=condition_id,
        token_id=token_id,
        shares=_decimal(record.get("shares"), Decimal("0")) or Decimal("0"),
        cost_usdc=_decimal(record.get("cost_usdc"), Decimal("0")) or Decimal("0"),
        market_slug=_text(record.get("market_slug")),
        open_buy_shares=_decimal(record.get("open_buy_shares"), Decimal("0")) or Decimal("0"),
        open_sell_shares=_decimal(record.get("open_sell_shares"), Decimal("0")) or Decimal("0"),
        pending_buy_shares=_decimal(record.get("pending_buy_shares"), Decimal("0")) or Decimal("0"),
        confirmed_shares=_decimal(record.get("confirmed_shares"), Decimal("0")) or Decimal("0"),
        last_order_id=_text(record.get("last_order_id")),
        last_trade_id=_text(record.get("last_trade_id")),
        confirmation_status=_text(record.get("confirmation_status")) or "unknown",
        updated_at=_datetime(record.get("updated_at") or record.get("created_at")),
    )


def _account_snapshot_from_record(record: Mapping[str, Any]) -> AccountSnapshot | None:
    balance_usdc = _decimal(record.get("balance_usdc"))
    allowance_usdc = _decimal(record.get("allowance_usdc"))
    if balance_usdc is None or allowance_usdc is None:
        _log_skip("account", record, "missing balance_usdc/allowance_usdc")
        return None
    return AccountSnapshot(
        balance_usdc=balance_usdc,
        allowance_usdc=allowance_usdc,
        user_ws_connected=_bool(record.get("user_ws_connected"), False),
        allow_new_entries=_bool(record.get("allow_new_entries"), False),
        paused_markets=_string_tuple(record.get("paused_markets")),
        pause_reasons=_pair_tuple(record.get("pause_reasons")),
        last_reconcile_at=_datetime(record.get("last_reconcile_at")),
    )


def _allocation_from_record(record: Mapping[str, Any]) -> Allocation | None:
    condition_id = _text(record.get("condition_id"))
    if condition_id is None:
        _log_skip("allocation", record, "missing condition_id")
        return None
    return Allocation(
        condition_id=condition_id,
        target_budget_usdc=_decimal(record.get("target_budget_usdc"), Decimal("0")) or Decimal("0"),
        buy_budget_usdc=_decimal(record.get("buy_budget_usdc"), Decimal("0")) or Decimal("0"),
        market_slug=_text(record.get("market_slug")),
        token_id=_text(record.get("token_id")),
        current_exposure_usdc=_decimal(record.get("current_exposure_usdc"), Decimal("0")) or Decimal("0"),
        released_budget_usdc=_decimal(record.get("released_budget_usdc"), Decimal("0")) or Decimal("0"),
        reason=_text(record.get("reason")) or "",
        idempotency_key=_text(record.get("idempotency_key")),
        release_reason=_text(record.get("release_reason")) or "",
    )


def _outbox_event_from_record(record: Mapping[str, Any]) -> OutboxEvent | None:
    trace_id = _text(record.get("trace_id"))
    event_type = _text(record.get("event_type"))
    idempotency_key = _text(record.get("idempotency_key"))
    if trace_id is None or event_type is None or idempotency_key is None:
        _log_skip("outbox", record, "missing trace_id/event_type/idempotency_key")
        return None
    payload = _mapping(record.get("outbox_payload")) or _mapping(record.get("raw_payload")) or dict(record)
    return OutboxEvent(
        trace_id=trace_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        event_id=_text(record.get("event_id")) or "",
        market_slug=_text(record.get("market_slug")),
        condition_id=_text(record.get("condition_id")),
        token_id=_text(record.get("token_id")),
        reason=_text(record.get("reason")),
        created_at=_datetime(record.get("created_at"), _utc_now()) or _utc_now(),
        priority=int(record.get("priority", 0)),
        retry_count=int(record.get("retry_count", 0)),
        last_error=_text(record.get("last_error")),
        raw_response_summary=_text(record.get("raw_response_summary")),
        payload=payload,
    )


@dataclass(frozen=True, slots=True)
class _RepositoryGroup:
    account: AccountSnapshotRepository
    audit: AuditEventRepository
    market: MarketRepository
    orderbook: OrderbookSnapshotRepository
    allocation: AllocationRepository
    order: OrderRepository
    fill: FillRepository
    position: PositionRepository
    outbox: OutboxEventRepository


class DatabasePersistenceRepository:
    """把 P3 持久化记录桥接到 typed repository。

    `PersistenceWorker` 消费的是结构化字典记录，而 DB 仓储要求 domain DTO。
    这里集中做一次字段收敛和 session/commit 管理，避免把转换逻辑塞回交易热路径。
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_audit_event(self, record: Mapping[str, Any]) -> int:
        return await self.save_audit_events([record])

    async def save_audit_events(self, records: Sequence[Mapping[str, Any]]) -> int:
        audit_events: list[AuditEvent] = []
        raw_payloads: list[dict[str, Any]] = []
        for record in records:
            audit_event = _audit_event_from_record(record)
            if audit_event is None:
                continue
            audit_events.append(audit_event)
            raw_payloads.append(dict(record))
        if not audit_events:
            return 0
        return await self._with_repositories(
            lambda repos: repos.audit.save_audit_events(audit_events, raw_payloads=raw_payloads)
        )

    async def save_market_snapshot(self, record: Mapping[str, Any]) -> int:
        return await self.save_market_snapshots([record])

    async def save_account_snapshot(self, record: Mapping[str, Any]) -> int:
        return await self.save_account_snapshots([record])

    async def save_account_snapshots(self, records: Sequence[Mapping[str, Any]]) -> int:
        grouped: dict[tuple[str | None], list[tuple[AccountSnapshot, dict[str, Any]]]] = {}
        for record in records:
            snapshot = _account_snapshot_from_record(record)
            if snapshot is None:
                continue
            key = (_text(record.get("trace_id")),)
            grouped.setdefault(key, []).append((snapshot, dict(record)))
        if not grouped:
            return 0

        async def write(repos: _RepositoryGroup) -> int:
            total = 0
            for (trace_id,), items in grouped.items():
                total += await repos.account.save_snapshots(
                    [item[0] for item in items],
                    trace_id=trace_id,
                    raw_payloads=[item[1] for item in items],
                )
            return total

        return await self._with_repositories(write)

    async def save_market_snapshots(self, records: Sequence[Mapping[str, Any]]) -> int:
        grouped: dict[tuple[str | None, str | None], list[tuple[Market, dict[str, Any]]]] = {}
        for record in records:
            market = _market_from_record(record)
            if market is None:
                continue
            key = (_text(record.get("trace_id")), _text(record.get("source")))
            grouped.setdefault(key, []).append((market, dict(record)))
        if not grouped:
            return 0

        async def write(repos: _RepositoryGroup) -> int:
            total = 0
            for (trace_id, source), items in grouped.items():
                total += await repos.market.save_markets(
                    [item[0] for item in items],
                    trace_id=trace_id,
                    source=source,
                    raw_payloads=[item[1] for item in items],
                )
            return total

        return await self._with_repositories(write)

    async def save_orderbook_snapshot(self, record: Mapping[str, Any]) -> int:
        return await self.save_orderbook_snapshots([record])

    async def save_orderbook_snapshots(self, records: Sequence[Mapping[str, Any]]) -> int:
        grouped: dict[
            tuple[str | None, str | None],
            list[tuple[OrderbookSnapshot, dict[str, Any]]],
        ] = {}
        for record in records:
            snapshot = _orderbook_from_record(record)
            if snapshot is None:
                continue
            key = (_text(record.get("trace_id")), _text(record.get("source")))
            grouped.setdefault(key, []).append((snapshot, dict(record)))
        if not grouped:
            return 0

        async def write(repos: _RepositoryGroup) -> int:
            total = 0
            for (trace_id, source), items in grouped.items():
                total += await repos.orderbook.save_snapshots(
                    [item[0] for item in items],
                    trace_id=trace_id,
                    source=source,
                    raw_payloads=[item[1] for item in items],
                )
            return total

        return await self._with_repositories(write)

    async def save_order(self, record: Mapping[str, Any]) -> int:
        return await self.save_orders([record])

    async def save_orders(self, records: Sequence[Mapping[str, Any]]) -> int:
        orders: list[Order] = []
        raw_payloads: list[dict[str, Any]] = []
        for record in records:
            order = _order_from_record(record)
            if order is None:
                continue
            orders.append(order)
            raw_payloads.append(dict(record))
        if not orders:
            return 0
        return await self._with_repositories(
            lambda repos: repos.order.save_orders(orders, raw_payloads=raw_payloads)
        )

    async def save_fill(self, record: Mapping[str, Any]) -> int:
        return await self.save_fills([record])

    async def save_fills(self, records: Sequence[Mapping[str, Any]]) -> int:
        fills: list[Fill] = []
        raw_payloads: list[dict[str, Any]] = []
        for record in records:
            fill = _fill_from_record(record)
            if fill is None:
                continue
            fills.append(fill)
            raw_payloads.append(dict(record))
        if not fills:
            return 0
        return await self._with_repositories(
            lambda repos: repos.fill.save_fills(fills, raw_payloads=raw_payloads)
        )

    async def save_position(self, record: Mapping[str, Any]) -> int:
        return await self.save_positions([record])

    async def save_positions(self, records: Sequence[Mapping[str, Any]]) -> int:
        grouped: dict[tuple[str | None], list[Position]] = {}
        raw_payloads: dict[tuple[str | None], list[dict[str, Any]]] = {}
        for record in records:
            position = _position_from_record(record)
            if position is None:
                continue
            key = (_text(record.get("trace_id")),)
            grouped.setdefault(key, []).append(position)
            raw_payloads.setdefault(key, []).append(dict(record))
        if not grouped:
            return 0

        async def write(repos: _RepositoryGroup) -> int:
            total = 0
            for (trace_id,), positions in grouped.items():
                total += await repos.position.save_positions(
                    positions,
                    trace_id=trace_id,
                    raw_payloads=raw_payloads[(trace_id,)],
                )
            return total

        return await self._with_repositories(write)

    async def save_allocation(self, record: Mapping[str, Any]) -> int:
        return await self.save_allocations([record])

    async def save_allocations(self, records: Sequence[Mapping[str, Any]]) -> int:
        grouped: dict[tuple[str | None], list[Allocation]] = {}
        raw_payloads: dict[tuple[str | None], list[dict[str, Any]]] = {}
        for record in records:
            allocation = _allocation_from_record(record)
            if allocation is None:
                continue
            key = (_text(record.get("trace_id")),)
            grouped.setdefault(key, []).append(allocation)
            raw_payloads.setdefault(key, []).append(dict(record))
        if not grouped:
            return 0

        async def write(repos: _RepositoryGroup) -> int:
            total = 0
            for (trace_id,), allocations in grouped.items():
                if trace_id is None:
                    continue
                total += await repos.allocation.save_allocations(
                    allocations,
                    trace_id=trace_id,
                    raw_payloads=raw_payloads[(trace_id,)],
                )
            return total

        return await self._with_repositories(write)

    async def save_outbox_event(self, record: Mapping[str, Any]) -> int:
        return await self.save_outbox_events([record])

    async def save_outbox_events(self, records: Sequence[Mapping[str, Any]]) -> int:
        events: list[OutboxEvent] = []
        raw_payloads: list[dict[str, Any]] = []
        for record in records:
            event = _outbox_event_from_record(record)
            if event is None:
                continue
            events.append(event)
            raw_payloads.append(dict(record))
        if not events:
            return 0
        return await self._with_repositories(
            lambda repos: repos.outbox.save_events(events, raw_payloads=raw_payloads)
        )

    async def _with_repositories(self, callback: Any) -> int:
        async with self._session_factory() as session:
            repositories = _RepositoryGroup(
                account=AccountSnapshotRepository(session),
                audit=AuditEventRepository(session),
                market=MarketRepository(session),
                orderbook=OrderbookSnapshotRepository(session),
                allocation=AllocationRepository(session),
                order=OrderRepository(session),
                fill=FillRepository(session),
                position=PositionRepository(session),
                outbox=OutboxEventRepository(session),
            )
            result = await callback(repositories)
            await session.commit()
            return int(result or 0)


__all__ = ["DatabasePersistenceRepository"]
