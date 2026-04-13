from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from polymarket_trader.domain.constants import ENTRY_NO_PRICE_MAX
from polymarket_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from polymarket_trader.domain.market import Market
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.runtime.event_bus import EventBus
from polymarket_trader.runtime.registry import MarketRegistry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: Any | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return None
    return Decimal(text)


def _first(mapping: Mapping[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _mapping(mapping: Mapping[str, Any], *keys: str) -> Mapping[str, Any] | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _bool(value: Any | None) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def _bps(value: Any | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = Decimal(text)
    except InvalidOperation:
        return None
    if numeric == numeric.to_integral_value():
        return int(numeric)
    if abs(numeric) < Decimal("1"):
        return int((numeric * Decimal("10000")).to_integral_value())
    return int(numeric.to_integral_value())


def _to_datetime(value: Any | None) -> datetime | None:
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


def _extract_token_id(message: Mapping[str, Any]) -> str | None:
    value = _first(
        message,
        "token_id",
        "tokenId",
        "asset_id",
        "assetId",
        "market_token_id",
        "winning_asset_id",
    )
    return None if value is None else str(value)


def _extract_sequence(message: Mapping[str, Any]) -> int | None:
    value = _first(message, "sequence", "seq", "version")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_levels(value: Any) -> tuple[PriceLevel, ...]:
    if not isinstance(value, list):
        return ()
    levels: list[PriceLevel] = []
    for item in value:
        if isinstance(item, Mapping):
            price = _decimal(_first(item, "price", "p"))
            size = _decimal(_first(item, "size", "quantity", "qty", "amount"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            price = _decimal(item[0])
            size = _decimal(item[1])
        else:
            continue
        if price is None or size is None:
            continue
        levels.append(PriceLevel(price=price, size=size))
    return tuple(levels)


def _message_type(message: Mapping[str, Any]) -> str:
    value = _first(message, "event_type", "message_type", "channel_event", "event", "type", "action")
    return "" if value is None else str(value).strip().lower()


def _extract_token_candidates(message: Mapping[str, Any]) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()
    direct = _extract_token_id(message)
    if direct is not None and direct not in seen:
        candidates.append(direct)
        seen.add(direct)
    for key in ("assets_ids", "clob_token_ids"):
        value = message.get(key)
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            text = str(item).strip()
            if text and text not in seen:
                candidates.append(text)
                seen.add(text)
    return tuple(candidates)


def _best_price(levels: tuple[PriceLevel, ...]) -> Decimal | None:
    if not levels:
        return None
    return max(level.price for level in levels)


def _worst_ask(levels: tuple[PriceLevel, ...]) -> Decimal | None:
    if not levels:
        return None
    return min(level.price for level in levels)


@dataclass(slots=True)
class _BookState:
    snapshot: OrderbookSnapshot
    last_sequence: int | None = None
    needs_rest_snapshot: bool = False
    entry_price_touched: bool = False
    resolved: bool = False
    subscribed_at: datetime | None = None
    last_message_at: datetime | None = None
    last_rest_snapshot_at: datetime | None = None
    last_error: str | None = None
    last_result: "MarketWsResultSummary" | None = None


@dataclass(frozen=True, slots=True)
class MarketWsResultSummary:
    token_id: str
    market_slug: str | None
    condition_id: str | None
    source: str
    reason: str
    event_types: tuple[str, ...]
    last_sequence: int | None
    entry_price_touched: bool
    resolved: bool
    needs_rest_snapshot: bool
    best_bid: Decimal | None
    best_ask: Decimal | None
    buyable_no_depth: Decimal
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class MarketWsSubscriptionStatus:
    token_id: str
    market_slug: str | None
    condition_id: str | None
    subscribed_at: datetime | None
    last_message_at: datetime | None
    last_rest_snapshot_at: datetime | None
    last_sequence: int | None
    entry_price_touched: bool
    resolved: bool
    needs_rest_snapshot: bool
    last_error: str | None


@dataclass(frozen=True, slots=True)
class MarketWsWorkerStatus:
    tracked_market_count: int
    subscription_count: int
    tracked_token_ids: tuple[str, ...]
    subscribed_token_ids: tuple[str, ...]
    entry_price_touched_token_ids: tuple[str, ...]
    resolved_token_ids: tuple[str, ...]
    needs_rest_snapshot_token_ids: tuple[str, ...]
    last_message_at: datetime | None
    last_rest_snapshot_at: datetime | None
    last_error: str | None
    last_result: MarketWsResultSummary | None
    recent_results: tuple[MarketWsResultSummary, ...]
    subscriptions: tuple[MarketWsSubscriptionStatus, ...]


@dataclass(frozen=True, slots=True)
class MarketWsEvent(DomainEvent):
    merge_key: str | None = None


class MarketWsWorker:
    priority = "P0"

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        registry: MarketRegistry | None = None,
        entry_price_max: Decimal = ENTRY_NO_PRICE_MAX,
        rest_snapshot_loader: Callable[
            [str],
            Awaitable[OrderbookSnapshot | Mapping[str, Any]],
        ]
        | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._registry = registry
        self._entry_price_max = entry_price_max
        self._rest_snapshot_loader = rest_snapshot_loader
        self._states: dict[str, _BookState] = {}
        self._tracked_markets: dict[str, Market] = {}
        self._recent_results: deque[MarketWsResultSummary] = deque(maxlen=8)
        self._last_message_at: datetime | None = None
        self._last_rest_snapshot_at: datetime | None = None
        self._last_error: str | None = None

    def track_market(self, market: Market) -> None:
        # 这里只做热态索引，不做数据库同步写；registry / cache 的更新都留在内存边界内。
        self._tracked_markets[market.no_token_id] = market
        if self._registry is not None:
            self._registry.upsert(market)
        if market.no_token_id not in self._states:
            self._states[market.no_token_id] = _BookState(
                snapshot=OrderbookSnapshot(
                    token_id=market.no_token_id,
                    best_bid=None,
                    best_ask=None,
                    bids=(),
                    asks=(),
                    received_at=_utc_now(),
                    market_slug=market.market_slug,
                    condition_id=market.condition_id,
                    tick_size=market.tick_size,
                ),
            )

    def untrack_market(self, no_token_id: str) -> None:
        token_id = str(no_token_id).strip()
        if not token_id:
            return
        self._tracked_markets.pop(token_id, None)
        self._states.pop(token_id, None)

    def build_subscription_request(
        self,
        no_token_id: str | tuple[str, ...] | list[str],
    ) -> dict[str, Any]:
        # 只订阅 NO token_id，避免把 YES side 的噪声带进入场信号链路。
        token_ids = (
            tuple(str(item).strip() for item in no_token_id if str(item).strip())
            if isinstance(no_token_id, (list, tuple))
            else ((str(no_token_id).strip(),) if str(no_token_id).strip() else ())
        )
        for token_id in token_ids:
            self._mark_subscribed(token_id)
        return {
            "assets_ids": list(token_ids),
            "type": "market",
            "custom_feature_enabled": True,
        }

    async def handle_message(
        self,
        message: Mapping[str, Any],
        *,
        source: str = "market_ws",
    ) -> list[DomainEvent]:
        self._last_message_at = _utc_now()
        message_type = _message_type(message)
        if message_type == "price_change" and isinstance(message.get("price_changes"), list):
            events: list[DomainEvent] = []
            for item in message["price_changes"]:
                if not isinstance(item, Mapping):
                    continue
                expanded = dict(message)
                expanded.pop("price_changes", None)
                expanded.update(item)
                expanded["event_type"] = "price_change"
                events.extend(await self.handle_message(expanded, source=source))
            return events

        token_id = self._resolve_token_id(message)
        if token_id is None:
            return []

        market = self._resolve_market(message, token_id)
        state = self._ensure_state(token_id, market)
        state.last_error = None
        self._last_error = None
        if state.resolved and message_type != "market_resolved":
            return []

        sequence = _extract_sequence(message)
        if self._sequence_gap_detected(state, sequence):
            state.needs_rest_snapshot = True
            if self._rest_snapshot_loader is not None:
                snapshot = await self._rest_snapshot_loader(token_id)
                return await self.apply_rest_snapshot(token_id, snapshot, source=source)
            self.record_error("rest_snapshot_loader_unavailable", token_id=token_id)
            return []

        if state.needs_rest_snapshot and message_type not in {"rest_snapshot", "snapshot", "book", "orderbook"}:
            return []
        events: list[DomainEvent] = []

        if message_type in {"book", "orderbook", "snapshot", "rest_snapshot"}:
            events.extend(await self._apply_book_message(token_id, state, message, source=source))
        elif message_type in {"price_change", "best_bid_ask", "best_bidask", "best_bid_and_ask"}:
            events.extend(await self._apply_price_message(token_id, state, message, source=source))
        elif message_type == "tick_size_change":
            events.extend(
                await self._apply_tick_size_change(
                    token_id,
                    state,
                    market,
                    message,
                    source=source,
                )
            )
        elif message_type == "last_trade_price":
            events.extend(
                await self._apply_last_trade_price(
                    token_id,
                    state,
                    market,
                    message,
                    source=source,
                )
            )
        elif message_type == "market_resolved":
            events.extend(
                await self._apply_market_resolved(token_id, state, message, source=source)
            )
        elif message_type == "new_market":
            events.extend(
                await self._apply_market_metadata(
                    token_id,
                    state,
                    market,
                    message,
                    source=source,
                )
            )
        else:
            # 高频 WS 里会有不少和 orderbook 无关的 control message，这里只忽略它们。
            return []

        state.last_sequence = sequence if sequence is not None else state.last_sequence
        return events

    async def apply_rest_snapshot(
        self,
        token_id: str,
        snapshot: OrderbookSnapshot | Mapping[str, Any],
        *,
        source: str = "rest_snapshot",
    ) -> list[DomainEvent]:
        self._last_rest_snapshot_at = _utc_now()
        market = self._tracked_markets.get(token_id) or self._resolve_market({}, token_id)
        current = self._states.get(token_id)
        snapshot_model = (
            snapshot
            if isinstance(snapshot, OrderbookSnapshot)
            else self._snapshot_from_mapping(
                token_id,
                snapshot,
                market=market,
                previous=current.snapshot if current is not None else None,
            )
        )
        self._states[token_id] = _BookState(
            snapshot=snapshot_model,
            last_sequence=_extract_sequence(snapshot) if isinstance(snapshot, Mapping) else None,
            needs_rest_snapshot=False,
            entry_price_touched=current.entry_price_touched if current is not None else False,
            resolved=current.resolved if current is not None else False,
            subscribed_at=current.subscribed_at if current is not None else None,
            last_message_at=_utc_now(),
            last_rest_snapshot_at=_utc_now(),
            last_error=current.last_error if current is not None else None,
        )
        return await self._emit_snapshot_update(
            token_id,
            self._states[token_id],
            source=source,
            reason="rest_snapshot",
        )

    def snapshot(self, token_id: str) -> OrderbookSnapshot | None:
        state = self._states.get(token_id)
        return None if state is None else state.snapshot

    def status_snapshot(self) -> MarketWsWorkerStatus:
        subscriptions: list[MarketWsSubscriptionStatus] = []
        tracked_token_ids = tuple(sorted(self._tracked_markets.keys()))
        subscribed_token_ids: list[str] = []
        entry_price_touched_token_ids: list[str] = []
        resolved_token_ids: list[str] = []
        needs_rest_snapshot_token_ids: list[str] = []
        last_error: str | None = self._last_error
        last_result: MarketWsResultSummary | None = None
        last_message_at = self._last_message_at
        last_rest_snapshot_at = self._last_rest_snapshot_at

        for token_id in tracked_token_ids:
            state = self._states.get(token_id)
            if state is None:
                continue
            if state.subscribed_at is not None:
                subscribed_token_ids.append(token_id)
            if state.entry_price_touched:
                entry_price_touched_token_ids.append(token_id)
            if state.resolved:
                resolved_token_ids.append(token_id)
            if state.needs_rest_snapshot:
                needs_rest_snapshot_token_ids.append(token_id)
            if state.last_error is not None and last_error is None:
                last_error = state.last_error
            if state.last_result is not None and (
                last_result is None or state.last_result.created_at > last_result.created_at
            ):
                last_result = state.last_result
            subscriptions.append(
                MarketWsSubscriptionStatus(
                    token_id=token_id,
                    market_slug=state.snapshot.market_slug,
                    condition_id=state.snapshot.condition_id,
                    subscribed_at=state.subscribed_at,
                    last_message_at=state.last_message_at,
                    last_rest_snapshot_at=state.last_rest_snapshot_at,
                    last_sequence=state.last_sequence,
                    entry_price_touched=state.entry_price_touched,
                    resolved=state.resolved,
                    needs_rest_snapshot=state.needs_rest_snapshot,
                    last_error=state.last_error,
                )
            )
            if state.last_message_at is not None and (
                last_message_at is None or state.last_message_at > last_message_at
            ):
                last_message_at = state.last_message_at
            if state.last_rest_snapshot_at is not None and (
                last_rest_snapshot_at is None or state.last_rest_snapshot_at > last_rest_snapshot_at
            ):
                last_rest_snapshot_at = state.last_rest_snapshot_at

        return MarketWsWorkerStatus(
            tracked_market_count=len(tracked_token_ids),
            subscription_count=len(subscribed_token_ids),
            tracked_token_ids=tracked_token_ids,
            subscribed_token_ids=tuple(subscribed_token_ids),
            entry_price_touched_token_ids=tuple(entry_price_touched_token_ids),
            resolved_token_ids=tuple(resolved_token_ids),
            needs_rest_snapshot_token_ids=tuple(needs_rest_snapshot_token_ids),
            last_message_at=last_message_at,
            last_rest_snapshot_at=last_rest_snapshot_at,
            last_error=last_error,
            last_result=last_result,
            recent_results=tuple(self._recent_results),
            subscriptions=tuple(subscriptions),
        )

    def record_error(self, reason: str, *, token_id: str | None = None) -> None:
        self._last_error = reason
        if token_id is not None:
            state = self._states.get(token_id)
            if state is not None:
                state.last_error = reason

    def buyable_depth(self, token_id: str, price_limit: Decimal | None = None) -> Decimal:
        state = self._states.get(token_id)
        if state is None:
            return Decimal("0")
        return state.snapshot.buyable_ask_depth(price_limit or self._entry_price_max)

    async def _apply_book_message(
        self,
        token_id: str,
        state: _BookState,
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        snapshot = self._snapshot_from_message(token_id, message, previous=state.snapshot)
        state.snapshot = snapshot
        state.needs_rest_snapshot = False
        return await self._emit_snapshot_update(token_id, state, source=source, reason="book")

    async def _apply_price_message(
        self,
        token_id: str,
        state: _BookState,
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        snapshot = state.snapshot
        best_bid = _decimal(_first(message, "best_bid", "bestBid", "bid"))
        best_ask = _decimal(_first(message, "best_ask", "bestAsk", "ask"))
        best_bid_size = _decimal(_first(message, "best_bid_size", "bestBidSize"))
        best_ask_size = _decimal(_first(message, "best_ask_size", "bestAskSize"))
        bids = snapshot.bids
        asks = snapshot.asks

        side = str(_first(message, "side", "book_side", "direction") or "").lower()
        price = _decimal(_first(message, "price", "new_price", "p"))
        size = _decimal(_first(message, "size", "new_size", "quantity", "qty"))
        if price is not None and size is not None:
            if side in {"bid", "buy", "yes"}:
                bids = self._upsert_level(bids, price, size)
                best_bid = best_bid or _best_price(bids)
                best_bid_size = best_bid_size or self._size_for_price(bids, best_bid)
            else:
                asks = self._upsert_level(asks, price, size)
                best_ask = best_ask or _worst_ask(asks)
                best_ask_size = best_ask_size or self._size_for_price(asks, best_ask)

        snapshot = replace(
            snapshot,
            best_bid=best_bid if best_bid is not None else snapshot.best_bid,
            best_ask=best_ask if best_ask is not None else snapshot.best_ask,
            best_bid_size=best_bid_size if best_bid_size is not None else snapshot.best_bid_size,
            best_ask_size=best_ask_size if best_ask_size is not None else snapshot.best_ask_size,
            bids=bids,
            asks=asks,
            received_at=_utc_now(),
        )
        state.snapshot = snapshot
        return await self._emit_snapshot_update(
            token_id,
            state,
            source=source,
            reason="price_change",
        )

    async def _apply_tick_size_change(
        self,
        token_id: str,
        state: _BookState,
        market: Market | None,
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        tick_size = _decimal(_first(message, "tick_size", "tickSize", "new_tick_size"))
        if tick_size is not None and market is not None and self._registry is not None:
            # tick size 变化要回写 Market Registry，热态路由依旧走内存对象，不碰数据库。
            try:
                self._registry.change_tick_size(market.condition_id, tick_size)
            except AttributeError:
                self._registry.upsert(replace(market, tick_size=tick_size))
            market = replace(market, tick_size=tick_size)
            self._tracked_markets[token_id] = market
        snapshot = replace(
            state.snapshot,
            tick_size=tick_size or state.snapshot.tick_size,
            received_at=_utc_now(),
        )
        state.snapshot = snapshot
        return await self._emit_snapshot_update(
            token_id,
            state,
            source=source,
            reason="tick_size_change",
        )

    async def _apply_last_trade_price(
        self,
        token_id: str,
        state: _BookState,
        market: Market | None,
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        last_trade_price = _decimal(_first(message, "last_trade_price", "lastTradePrice", "price"))
        if last_trade_price is None:
            return []
        events: list[DomainEvent] = []
        fee_rate_bps = _bps(_first(message, "fee_rate_bps", "feeRateBps"))
        updated_at = _to_datetime(_first(message, "timestamp", "updated_at", "updatedAt")) or _utc_now()
        if market is not None and fee_rate_bps is not None:
            updated_market = self._update_market_fee_rate(
                token_id,
                market,
                fee_rate_bps,
                updated_at=updated_at,
            )
            if updated_market is not None:
                market = updated_market
                events.append(
                    await self._publish_market_update(
                        updated_market,
                        source=source,
                        reason="last_trade_price",
                        message=message,
                    )
                )
        state.snapshot = replace(
            state.snapshot,
            last_trade_price=last_trade_price,
            received_at=_utc_now(),
        )
        events.extend(
            await self._emit_snapshot_update(
                token_id,
                state,
                source=source,
                reason="last_trade_price",
            )
        )
        return events

    async def _apply_market_resolved(
        self,
        token_id: str,
        state: _BookState,
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        state.resolved = True
        state.snapshot = replace(state.snapshot, received_at=_utc_now())
        market = self._tracked_markets.get(token_id)
        if market is not None and self._registry is not None:
            resolved_market = self._registry.mark_resolved(market.condition_id)
            if resolved_market is not None:
                self._tracked_markets[token_id] = resolved_market
        event = MarketWsEvent(
            trace_id=uuid4().hex,
            event_type=DomainEventType.MARKET_RESOLVED_OR_DISABLED,
            event_id=uuid4().hex,
            token_id=token_id,
            market_slug=state.snapshot.market_slug,
            condition_id=state.snapshot.condition_id,
            reason=str(_first(message, "reason", "status") or "market_resolved"),
            created_at=state.snapshot.received_at,
            merge_key=f"market_resolved_or_disabled|{token_id}",
            payload={
                "source": source,
                "snapshot": self._snapshot_payload(state.snapshot),
                "message": dict(message),
            },
        )
        return [await self._publish(OutboxPriority.P0, event)]

    async def _apply_market_metadata(
        self,
        token_id: str,
        state: _BookState,
        market: Market | None,
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        if market is not None:
            updated_market = self._update_market_fee_schedule(token_id, market, message)
            if updated_market is not None:
                market = updated_market
                events.append(
                    await self._publish_market_update(
                        updated_market,
                        source=source,
                        reason="new_market",
                        message=message,
                    )
                )
            elif self._registry is not None:
                self._registry.upsert(market)
        state.snapshot = replace(state.snapshot, received_at=_utc_now())
        events.extend(
            await self._emit_snapshot_update(token_id, state, source=source, reason="new_market")
        )
        return events

    async def _emit_snapshot_update(
        self,
        token_id: str,
        state: _BookState,
        *,
        source: str,
        reason: str,
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        snapshot = state.snapshot
        event = MarketWsEvent(
            trace_id=uuid4().hex,
            event_type=DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED,
            event_id=uuid4().hex,
            token_id=token_id,
            market_slug=snapshot.market_slug,
            condition_id=snapshot.condition_id,
            reason=reason,
            created_at=snapshot.received_at,
            merge_key=f"orderbook_snapshot_updated|{token_id}",
            payload={
                "source": source,
                "snapshot": self._snapshot_payload(snapshot),
                "spread": self._serialize_decimal(snapshot.spread),
                "buyable_no_depth": self._serialize_decimal(
                    snapshot.buyable_ask_depth(self._entry_price_max)
                ),
                "snapshot_time": snapshot.snapshot_time.isoformat(),
                "needs_rest_snapshot": state.needs_rest_snapshot,
            },
        )
        events.append(await self._publish(OutboxPriority.P2, event))

        if (
            not state.entry_price_touched
            and snapshot.token_id == token_id
            and snapshot.no_entry_touched(self._entry_price_max)
        ):
            # NO ask 侧首次穿越 0.60 立即送到 P0，后续相同价格只做普通快照，不重复打点。
            state.entry_price_touched = True
            touched = MarketWsEvent(
                trace_id=event.trace_id,
                event_type=DomainEventType.ENTRY_PRICE_TOUCHED,
                event_id=uuid4().hex,
                token_id=token_id,
                market_slug=snapshot.market_slug,
                condition_id=snapshot.condition_id,
                reason="no_best_ask_touched",
                created_at=snapshot.received_at,
                merge_key=f"entry_price_touched|{token_id}",
                payload={
                    "source": source,
                    "snapshot": self._snapshot_payload(snapshot),
                    "entry_price_max": self._serialize_decimal(self._entry_price_max),
                    "buyable_no_depth": self._serialize_decimal(
                        snapshot.buyable_ask_depth(self._entry_price_max)
                    ),
                    "snapshot_time": snapshot.snapshot_time.isoformat(),
                },
            )
            events.append(await self._publish(OutboxPriority.P0, touched))
        self._record_result(
            token_id,
            state,
            source=source,
            reason=reason,
            event_types=tuple(str(event.event_type) for event in events),
        )
        return events

    async def _publish(self, priority: OutboxPriority, event: DomainEvent) -> DomainEvent:
        if self._event_bus is not None:
            await self._event_bus.publish(priority, event)
        return event

    def _record_result(
        self,
        token_id: str,
        state: _BookState,
        *,
        source: str,
        reason: str,
        event_types: tuple[str, ...],
    ) -> None:
        snapshot = state.snapshot
        result = MarketWsResultSummary(
            token_id=token_id,
            market_slug=snapshot.market_slug,
            condition_id=snapshot.condition_id,
            source=source,
            reason=reason,
            event_types=event_types,
            last_sequence=state.last_sequence,
            entry_price_touched=state.entry_price_touched,
            resolved=state.resolved,
            needs_rest_snapshot=state.needs_rest_snapshot,
            best_bid=snapshot.best_bid,
            best_ask=snapshot.best_ask,
            buyable_no_depth=snapshot.buyable_ask_depth(self._entry_price_max),
        )
        state.last_message_at = snapshot.received_at
        state.last_result = result
        if reason in {"rest_snapshot", "reconcile_rest"}:
            state.last_rest_snapshot_at = snapshot.received_at
            self._last_rest_snapshot_at = snapshot.received_at
        self._last_message_at = snapshot.received_at
        self._recent_results.append(result)

    def _mark_subscribed(self, token_id: str) -> None:
        state = self._states.get(token_id)
        if state is None:
            return
        if state.subscribed_at is None:
            state.subscribed_at = _utc_now()

    def _ensure_state(self, token_id: str, market: Market | None) -> _BookState:
        state = self._states.get(token_id)
        if state is not None:
            return state
        snapshot = OrderbookSnapshot(
            token_id=token_id,
            best_bid=None,
            best_ask=None,
            bids=(),
            asks=(),
            received_at=_utc_now(),
            market_slug=market.market_slug if market is not None else None,
            condition_id=market.condition_id if market is not None else None,
            tick_size=market.tick_size if market is not None else None,
        )
        state = _BookState(snapshot=snapshot)
        self._states[token_id] = state
        return state

    def _resolve_token_id(self, message: Mapping[str, Any]) -> str | None:
        candidates = _extract_token_candidates(message)
        if not candidates:
            return None
        for token_id in candidates:
            if token_id in self._tracked_markets or token_id in self._states:
                return token_id
            if self._registry is not None and self._registry.get_by_no_token_id(token_id) is not None:
                return token_id
        return candidates[0]

    def _resolve_market(self, message: Mapping[str, Any], token_id: str) -> Market | None:
        if token_id in self._tracked_markets:
            return self._tracked_markets[token_id]
        condition_id = _first(message, "condition_id", "conditionId", "market")
        market_slug = _first(message, "market_slug", "marketSlug", "slug")
        if self._registry is not None:
            if condition_id:
                market = self._registry.get_by_condition_id(str(condition_id))
                if market is not None:
                    self._tracked_markets[token_id] = market
                    return market
            market = self._registry.get_by_no_token_id(token_id)
            if market is not None:
                self._tracked_markets[token_id] = market
                return market
            if market_slug:
                market = self._registry.get_by_slug(str(market_slug))
                if market is not None:
                    self._tracked_markets[token_id] = market
                    return market
        return None

    def _snapshot_from_message(
        self,
        token_id: str,
        message: Mapping[str, Any],
        *,
        previous: OrderbookSnapshot | None = None,
    ) -> OrderbookSnapshot:
        book = _first(message, "book", "orderbook", "snapshot", "rest_snapshot")
        payload = book if isinstance(book, Mapping) else message
        bids = _parse_levels(_first(payload, "bids", "yes_bids"))
        asks = _parse_levels(_first(payload, "asks", "no_asks"))
        best_bid = _decimal(_first(payload, "best_bid", "bestBid")) or _best_price(bids)
        best_ask = _decimal(_first(payload, "best_ask", "bestAsk")) or _worst_ask(asks)
        best_bid_size = _decimal(_first(payload, "best_bid_size", "bestBidSize"))
        best_ask_size = _decimal(_first(payload, "best_ask_size", "bestAskSize"))
        if best_bid_size is None and best_bid is not None:
            best_bid_size = self._size_for_price(bids, best_bid)
        if best_ask_size is None and best_ask is not None:
            best_ask_size = self._size_for_price(asks, best_ask)
        market_slug = str(
            _first(payload, "market_slug", "marketSlug", "slug")
            or (previous.market_slug if previous else "")
        ) or None
        condition_id = str(
            _first(payload, "condition_id", "conditionId", "market")
            or (previous.condition_id if previous else "")
        ) or None
        tick_size = _decimal(_first(payload, "tick_size", "tickSize")) or (
            previous.tick_size if previous else None
        )
        last_trade_price = _decimal(_first(payload, "last_trade_price", "lastTradePrice")) or (
            previous.last_trade_price if previous else None
        )
        return OrderbookSnapshot(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            bids=bids,
            asks=asks,
            received_at=_utc_now(),
            market_slug=market_slug,
            condition_id=condition_id,
            best_bid_size=best_bid_size,
            best_ask_size=best_ask_size,
            last_trade_price=last_trade_price,
            tick_size=tick_size,
        )

    def _snapshot_from_mapping(
        self,
        token_id: str,
        payload: Mapping[str, Any],
        *,
        market: Market | None = None,
        previous: OrderbookSnapshot | None = None,
    ) -> OrderbookSnapshot:
        if previous is None and market is not None:
            previous = OrderbookSnapshot(
                token_id=token_id,
                best_bid=None,
                best_ask=None,
                bids=(),
                asks=(),
                received_at=_utc_now(),
                market_slug=market.market_slug,
                condition_id=market.condition_id,
                tick_size=market.tick_size,
            )
        return self._snapshot_from_message(token_id, payload, previous=previous)

    def _sequence_gap_detected(self, state: _BookState, sequence: int | None) -> bool:
        if sequence is None:
            return False
        if state.last_sequence is None:
            return False
        return sequence > state.last_sequence + 1

    def _upsert_level(
        self,
        levels: tuple[PriceLevel, ...],
        price: Decimal,
        size: Decimal,
    ) -> tuple[PriceLevel, ...]:
        updated: list[PriceLevel] = []
        replaced = False
        for level in levels:
            if level.price == price:
                updated.append(PriceLevel(price=price, size=size))
                replaced = True
            else:
                updated.append(level)
        if not replaced:
            updated.append(PriceLevel(price=price, size=size))
        return tuple(updated)

    def _size_for_price(
        self,
        levels: tuple[PriceLevel, ...],
        price: Decimal | None,
    ) -> Decimal | None:
        if price is None:
            return None
        for level in levels:
            if level.price == price:
                return level.size
        return None

    def _snapshot_payload(self, snapshot: OrderbookSnapshot) -> dict[str, Any]:
        return {
            "token_id": snapshot.token_id,
            "market_slug": snapshot.market_slug,
            "condition_id": snapshot.condition_id,
            "best_bid": self._serialize_decimal(snapshot.best_bid),
            "best_ask": self._serialize_decimal(snapshot.best_ask),
            "best_bid_size": self._serialize_decimal(snapshot.best_bid_size),
            "best_ask_size": self._serialize_decimal(snapshot.best_ask_size),
            "last_trade_price": self._serialize_decimal(snapshot.last_trade_price),
            "tick_size": self._serialize_decimal(snapshot.tick_size),
            "spread": self._serialize_decimal(snapshot.spread),
            "buyable_no_depth": self._serialize_decimal(
                snapshot.buyable_ask_depth(self._entry_price_max),
            ),
            "received_at": snapshot.received_at.isoformat(),
            "snapshot_time": snapshot.snapshot_time.isoformat(),
        }

    def _market_payload(self, market: Market) -> dict[str, Any]:
        return {
            "condition_id": market.condition_id,
            "market_slug": market.market_slug,
            "event_slug": market.event_slug,
            "event_id": market.event_id,
            "event_title": market.event_title,
            "no_token_id": market.no_token_id,
            "yes_token_id": market.yes_token_id,
            "tick_size": self._serialize_decimal(market.tick_size),
            "min_order_size": self._serialize_decimal(market.min_order_size),
            "neg_risk": market.neg_risk,
            "fees": {
                "enabled": market.fees_enabled,
                "maker_base_fee_bps": market.maker_base_fee_bps,
                "taker_base_fee_bps": market.taker_base_fee_bps,
                "fee_rate_bps": market.fee_rate_bps,
                "fee_rate_updated_at": (
                    None if market.fee_rate_updated_at is None else market.fee_rate_updated_at.isoformat()
                ),
            },
            "category": market.category,
            "tags": list(market.tags),
            "matched_keywords": list(market.matched_keywords),
            "trading_status": market.trading_status.value,
            "reject_reason": market.reject_reason,
        }

    def _update_market_fee_schedule(
        self,
        token_id: str,
        market: Market,
        message: Mapping[str, Any],
    ) -> Market | None:
        fee_schedule = _mapping(message, "fee_schedule", "feeSchedule")
        fees_enabled = _bool(_first(message, "fees_enabled", "feesEnabled"))
        if fees_enabled is None and fee_schedule is not None:
            fees_enabled = _bool(_first(fee_schedule, "enabled", "feesEnabled"))
        maker_base_fee_bps = _bps(
            _first(
                message,
                "maker_base_fee_bps",
                "makerBaseFee",
                "maker_base_fee",
            )
        )
        taker_base_fee_bps = _bps(
            _first(
                message,
                "taker_base_fee_bps",
                "takerBaseFee",
                "taker_base_fee",
            )
        )
        if taker_base_fee_bps is None and fee_schedule is not None:
            taker_base_fee_bps = _bps(_first(fee_schedule, "rate", "base_fee", "baseFee"))
        updated_market = market.with_fee_schedule(
            fees_enabled=fees_enabled,
            maker_base_fee_bps=maker_base_fee_bps,
            taker_base_fee_bps=taker_base_fee_bps,
        )
        if updated_market == market:
            return None
        if self._registry is not None:
            refreshed = self._registry.update_fee_schedule(
                market.condition_id,
                fees_enabled=updated_market.fees_enabled,
                maker_base_fee_bps=updated_market.maker_base_fee_bps,
                taker_base_fee_bps=updated_market.taker_base_fee_bps,
            )
            if refreshed is not None:
                updated_market = refreshed
        self._tracked_markets[token_id] = updated_market
        return updated_market

    def _update_market_fee_rate(
        self,
        token_id: str,
        market: Market,
        fee_rate_bps: int,
        *,
        updated_at: datetime,
    ) -> Market | None:
        if market.fee_rate_bps == fee_rate_bps and market.fee_rate_updated_at is not None:
            return None
        updated_market = market.with_fee_rate(
            fee_rate_bps,
            fee_rate_updated_at=updated_at,
        )
        if updated_market == market:
            return None
        if self._registry is not None:
            refreshed = self._registry.update_fee_rate(
                market.condition_id,
                fee_rate_bps,
                fee_rate_updated_at=updated_at,
            )
            if refreshed is not None:
                updated_market = refreshed
        self._tracked_markets[token_id] = updated_market
        return updated_market

    async def _publish_market_update(
        self,
        market: Market,
        *,
        source: str,
        reason: str,
        message: Mapping[str, Any],
    ) -> DomainEvent:
        event = MarketWsEvent(
            trace_id=uuid4().hex,
            event_type=DomainEventType.MARKET_UPDATED,
            event_id=uuid4().hex,
            token_id=market.no_token_id,
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            reason=reason,
            created_at=_utc_now(),
            merge_key=f"market_updated|{market.condition_id}",
            payload={
                "source": source,
                "market": self._market_payload(market),
                "message": dict(message),
            },
        )
        return await self._publish(OutboxPriority.P2, event)

    def _serialize_decimal(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        return format(value, "f")
