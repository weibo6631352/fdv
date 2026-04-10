from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from fdv_trader.domain.constants import ENTRY_NO_PRICE_MAX
from fdv_trader.domain.events import DomainEvent, DomainEventType, OutboxPriority
from fdv_trader.domain.market import Market
from fdv_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from fdv_trader.runtime.event_bus import EventBus
from fdv_trader.runtime.registry import MarketRegistry


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


def _extract_token_id(message: Mapping[str, Any]) -> str | None:
    value = _first(message, "token_id", "tokenId", "asset_id", "assetId", "market_token_id")
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
                )
            )

    def build_subscription_request(self, no_token_id: str) -> dict[str, Any]:
        # 只订阅 NO token_id，避免把 YES side 的噪声带进入场信号链路。
        return {
            "channel": "market",
            "token_ids": [no_token_id],
            "custom_feature_enabled": True,
        }

    async def handle_message(
        self,
        message: Mapping[str, Any],
        *,
        source: str = "market_ws",
    ) -> list[DomainEvent]:
        token_id = _extract_token_id(message)
        if token_id is None:
            return []

        market = self._resolve_market(message, token_id)
        state = self._ensure_state(token_id, market)
        if state.resolved and message.get("type") != "market_resolved":
            return []

        sequence = _extract_sequence(message)
        if self._sequence_gap_detected(state, sequence):
            state.needs_rest_snapshot = True
            if self._rest_snapshot_loader is not None:
                snapshot = await self._rest_snapshot_loader(token_id)
                return await self.apply_rest_snapshot(token_id, snapshot, source=source)
            return []

        if state.needs_rest_snapshot and message.get("type") not in {"rest_snapshot", "snapshot"}:
            return []

        message_type = str(
            _first(message, "type", "event_type", "message_type", "channel_event") or ""
        ).lower()
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
                await self._apply_last_trade_price(token_id, state, message, source=source)
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
        message: Mapping[str, Any],
        *,
        source: str,
    ) -> list[DomainEvent]:
        last_trade_price = _decimal(_first(message, "last_trade_price", "lastTradePrice", "price"))
        if last_trade_price is None:
            return []
        state.snapshot = replace(
            state.snapshot,
            last_trade_price=last_trade_price,
            received_at=_utc_now(),
        )
        return await self._emit_snapshot_update(
            token_id,
            state,
            source=source,
            reason="last_trade_price",
        )

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
        if market is not None and self._registry is not None:
            self._registry.upsert(market)
        state.snapshot = replace(state.snapshot, received_at=_utc_now())
        return await self._emit_snapshot_update(token_id, state, source=source, reason="new_market")

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
        return events

    async def _publish(self, priority: OutboxPriority, event: DomainEvent) -> DomainEvent:
        if self._event_bus is not None:
            await self._event_bus.publish(priority, event)
        return event

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

    def _resolve_market(self, message: Mapping[str, Any], token_id: str) -> Market | None:
        if token_id in self._tracked_markets:
            return self._tracked_markets[token_id]
        condition_id = _first(message, "condition_id", "conditionId")
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
            _first(payload, "condition_id", "conditionId")
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

    def _serialize_decimal(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        return format(value, "f")
