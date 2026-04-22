from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from polymarket_trader.domain.events import AuditEvent, DomainEventType, OutboxEvent
from polymarket_trader.serialization import jsonable

_MARKET_EVENT_TYPES = {
    DomainEventType.MARKET_DISCOVERED.value,
    DomainEventType.MARKET_UPDATED.value,
    DomainEventType.MARKET_FILTERED_IN.value,
    DomainEventType.MARKET_FILTERED_OUT.value,
    DomainEventType.MARKET_RESOLVED_OR_DISABLED.value,
}
_ACCOUNT_EVENT_TYPES = {DomainEventType.BALANCE_UPDATED.value}
_ORDERBOOK_EVENT_TYPES = {
    DomainEventType.ORDERBOOK.value,
    DomainEventType.ORDERBOOK_SNAPSHOT_UPDATED.value,
}
_ORDER_EVENT_TYPES = {
    DomainEventType.ORDER_CREATED.value,
    DomainEventType.ORDER_SIGNED.value,
    DomainEventType.ORDER_SUBMITTED.value,
    DomainEventType.ORDER_REJECTED.value,
    DomainEventType.ORDER_MATCHED.value,
    DomainEventType.ORDER_NO_FILL.value,
    DomainEventType.ORDER_PARTIALLY_FILLED.value,
    DomainEventType.ORDER_STATE_UPDATED.value,
    DomainEventType.ORDER_CANCEL_REQUESTED.value,
    DomainEventType.ORDER_CANCELLED.value,
    DomainEventType.REPLACE_ORDER_SUBMITTED.value,
    DomainEventType.UNEXPECTED_RESTING_ORDER_DETECTED.value,
}
_FILL_EVENT_TYPES = {
    DomainEventType.FILL_RECORDED.value,
    DomainEventType.TRADE_MINED.value,
    DomainEventType.TRADE_CONFIRMED.value,
}
_POSITION_EVENT_TYPES = {DomainEventType.POSITION_UPDATED.value}


@dataclass(frozen=True, slots=True)
class PersistencePlannedRecord:
    event: OutboxEvent
    kind: str
    record: Mapping[str, Any]


class PersistenceRecordBuilder:
    def build_planned_records(
        self,
        events: Sequence[OutboxEvent],
    ) -> tuple[list[PersistencePlannedRecord], dict[str, int]]:
        planned_records: list[PersistencePlannedRecord] = []
        required_record_counts: dict[str, int] = {}
        for event in events:
            event_records = self.route_event(event)
            required_record_counts[event.event_id] = len(event_records)
            for kind, record in event_records:
                planned_records.append(PersistencePlannedRecord(event=event, kind=kind, record=record))
        return planned_records, required_record_counts

    def route_event(self, event: OutboxEvent) -> list[tuple[str, Mapping[str, Any]]]:
        records: list[tuple[str, Mapping[str, Any]]] = []
        event_type = _event_type_text(event)
        payload = dict(event.payload)

        records.append(("audit", self._build_audit_record(event, payload)))
        for record in self._build_allocation_records(event, payload):
            records.append(("allocation", record))

        if event_type in _MARKET_EVENT_TYPES:
            records.append(("market", self._build_market_record(event, payload)))
        if event_type in _ACCOUNT_EVENT_TYPES:
            records.append(("account", self._build_account_record(event, payload)))
        if event_type in _ORDERBOOK_EVENT_TYPES:
            records.append(("orderbook", self._build_orderbook_record(event, payload)))
        if event_type in _ORDER_EVENT_TYPES:
            records.append(("order", self._build_order_record(event, payload)))
        if event_type in _FILL_EVENT_TYPES:
            records.extend(("fill", record) for record in self._build_fill_records(event, payload))
        if event_type in _POSITION_EVENT_TYPES:
            records.extend(("position", record) for record in self._build_position_records(event, payload))

        records.append(("outbox", self._build_outbox_record(event, payload)))
        return records

    def _build_audit_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        audit = AuditEvent(
            event_title=str(event.event_type),
            trace_id=event.trace_id,
            event_id=event.event_id,
            market_slug=event.market_slug,
            condition_id=event.condition_id,
            token_id=event.token_id,
            reason=event.reason or "",
            created_at=event.created_at,
            raw_response=event.raw_response_summary,
            payload={
                "source_event_id": event.event_id,
                "source_event_type": str(event.event_type),
                "source_payload": jsonable(payload),
                "idempotency_key": event.idempotency_key,
                "priority": event.priority,
                "retry_count": event.retry_count,
            },
        )
        record = audit.to_payload()
        record["idempotency_key"] = _kind_idempotency_key("audit", event)
        record["source_event_id"] = event.event_id
        record["source_event_type"] = str(event.event_type)
        record["source_payload"] = jsonable(payload)
        return jsonable(record)

    def _build_market_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        market = _mapping(payload, "market", "market_snapshot")
        fees = _mapping(market or {}, "fees") or {}
        if market is None:
            fees = {
                "enabled": _first(payload, "fees_enabled"),
                "maker_base_fee_bps": _first(payload, "maker_base_fee_bps"),
                "taker_base_fee_bps": _first(payload, "taker_base_fee_bps"),
                "fee_rate_bps": _first(payload, "fee_rate_bps"),
                "fee_rate_updated_at": _first(payload, "fee_rate_updated_at"),
            }
            market = {
                "condition_id": event.condition_id,
                "market_slug": event.market_slug,
                "event_id": _first(payload, "event_id", "source_event_id"),
                "event_title": _first(payload, "event_title", "title"),
                "event_slug": _first(payload, "event_slug", "slug"),
                "icon_url": _first(payload, "icon_url", "icon"),
                "end_date": _first(payload, "end_date", "endDate"),
                "token_ids": _first(payload, "token_ids"),
                "outcomes": _first(payload, "outcomes"),
                "tick_size": _first(payload, "tick_size"),
                "min_order_size": _first(payload, "min_order_size"),
                "neg_risk": _first(payload, "neg_risk"),
                "fees": fees,
                "category": _first(payload, "category"),
                "tags": _first(payload, "tags"),
                "matched_keywords": _first(payload, "matched_keywords"),
                "trading_status": "rejected" if _first(payload, "accepted") is False else _first(payload, "trading_status"),
                "reject_reason": _first(payload, "reject_reason", "parse_reason", "classification_reason"),
            }

        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("market", event),
                "source": _first(payload, "source"),
                "discovery_kind": _first(payload, "discovery_kind"),
                "parse_status": _first(payload, "parse_status"),
                "parse_reason": _first(payload, "parse_reason"),
                "parse_detail": _first(payload, "parse_detail"),
                "matched_fields": jsonable(_first(payload, "matched_fields")),
                "matched_keywords": jsonable(_first(payload, "matched_keywords")),
                "accepted": _first(payload, "accepted"),
                "fees_enabled": _first(fees, "enabled"),
                "maker_base_fee_bps": _first(fees, "maker_base_fee_bps"),
                "taker_base_fee_bps": _first(fees, "taker_base_fee_bps"),
                "fee_rate_bps": _first(fees, "fee_rate_bps"),
                "fee_rate_updated_at": _first(fees, "fee_rate_updated_at"),
                "market_data": jsonable(market),
            }
        )
        record.update(jsonable(market))
        return record

    def _build_account_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = _base_meta(event)
        account = {
            "account_key": "primary",
            "balance_usdc": _first(payload, "balance_usdc"),
            "allowance_usdc": _first(payload, "allowance_usdc"),
            "user_ws_connected": _first(payload, "user_ws_connected"),
            "allow_new_entries": _first(payload, "allow_new_entries"),
            "paused_markets": _first(payload, "paused_markets"),
            "pause_reasons": _first(payload, "pause_reasons"),
            "last_reconcile_at": _first(payload, "last_reconcile_at"),
        }
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("account", event),
                "account_data": jsonable(account),
            }
        )
        record.update(jsonable(account))
        return record

    def _build_orderbook_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = _mapping(payload, "snapshot", "orderbook", "book")
        if snapshot is None:
            snapshot = {
                "token_id": event.token_id,
                "market_slug": event.market_slug,
                "condition_id": event.condition_id,
                "best_bid": _first(payload, "best_bid"),
                "best_ask": _first(payload, "best_ask"),
                "best_bid_size": _first(payload, "best_bid_size"),
                "best_ask_size": _first(payload, "best_ask_size"),
                "last_trade_price": _first(payload, "last_trade_price"),
                "tick_size": _first(payload, "tick_size"),
                "spread": _first(payload, "spread"),
                "buyable_no_depth": _first(payload, "buyable_no_depth"),
                "snapshot_time": _first(payload, "snapshot_time"),
                "needs_rest_snapshot": _first(payload, "needs_rest_snapshot"),
            }

        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("orderbook", event),
                "source": _first(payload, "source"),
                "snapshot_time": _first(payload, "snapshot_time"),
                "needs_rest_snapshot": _first(payload, "needs_rest_snapshot"),
                "spread": _first(payload, "spread"),
                "buyable_no_depth": _first(payload, "buyable_no_depth"),
                "orderbook_data": jsonable(snapshot),
            }
        )
        record.update(jsonable(snapshot))
        return record

    def _build_order_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        order = _mapping(payload, "order")
        if order is None:
            order = {
                "order_id": _first(payload, "order_id"),
                "trade_id": _first(payload, "trade_id"),
                "side": _first(payload, "side"),
                "order_type": _first(payload, "order_type"),
                "price": _first(payload, "price"),
                "amount_usdc": _first(payload, "amount_usdc"),
                "size_shares": _first(payload, "size_shares"),
                "filled_shares": _first(payload, "filled_shares"),
                "remaining_shares": _first(payload, "remaining_shares"),
                "notional_usdc": _first(payload, "notional_usdc"),
                "status": _first(payload, "status"),
                "reason": _first(payload, "reason"),
                "post_only": _first(payload, "post_only"),
            }

        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": _kind_idempotency_key("order", event),
                "order_data": jsonable(order),
            }
        )
        record.update(jsonable(order))
        return record

    def _build_fill_records(self, event: OutboxEvent, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        fills = _mapping_list(payload, "fill", "fills")
        if not fills:
            fills = [
                {
                    "event_id": event.event_id,
                    "trade_id": _first(payload, "trade_id"),
                    "order_id": _first(payload, "order_id"),
                    "side": _first(payload, "side"),
                    "price": _first(payload, "price"),
                    "size": _first(payload, "size"),
                    "notional_usdc": _first(payload, "notional_usdc"),
                    "status": _first(payload, "status"),
                    "confirmed_at": _first(payload, "confirmed_at"),
                }
            ]
        return [_indexed_record(event, "fill", index, "fill_data", fill) for index, fill in enumerate(fills)]

    def _build_position_records(self, event: OutboxEvent, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        positions = _mapping_list(payload, "position", "positions")
        if not positions:
            positions = [
                {
                    "condition_id": event.condition_id,
                    "token_id": event.token_id,
                    "market_slug": event.market_slug,
                    "shares": _first(payload, "shares"),
                    "cost_usdc": _first(payload, "cost_usdc"),
                    "open_buy_shares": _first(payload, "open_buy_shares"),
                    "open_sell_shares": _first(payload, "open_sell_shares"),
                    "pending_buy_shares": _first(payload, "pending_buy_shares"),
                    "confirmed_shares": _first(payload, "confirmed_shares"),
                    "last_order_id": _first(payload, "last_order_id"),
                    "last_trade_id": _first(payload, "last_trade_id"),
                    "confirmation_status": _first(payload, "confirmation_status"),
                }
            ]
        return [_indexed_record(event, "position", index, "position_data", item) for index, item in enumerate(positions)]

    def _build_allocation_records(self, event: OutboxEvent, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        allocation = _mapping(payload, "allocation")
        allocations = _mapping_list(payload, "allocations")
        plan = _mapping(payload, "allocation_plan")

        if allocation is None and allocations:
            records_source = allocations
        elif allocation is not None:
            records_source = [allocation]
        elif plan is not None and isinstance(plan.get("allocations"), list):
            records_source = [item for item in plan["allocations"] if isinstance(item, Mapping)]
        else:
            return []

        records: list[dict[str, Any]] = []
        plan_meta = jsonable(plan) if plan is not None else None
        for index, allocation_item in enumerate(records_source):
            record = _base_meta(event)
            record.update(
                {
                    "idempotency_key": _kind_idempotency_key("allocation", event),
                    "allocation_index": index,
                    "allocation_plan": plan_meta,
                    "allocation_data": jsonable(allocation_item),
                }
            )
            record.update(jsonable(allocation_item))
            records.append(record)
        return records

    def _build_outbox_record(self, event: OutboxEvent, payload: Mapping[str, Any]) -> dict[str, Any]:
        record = _base_meta(event)
        record.update(
            {
                "idempotency_key": event.idempotency_key,
                "outbox_payload": jsonable(payload),
            }
        )
        return record


def route_key(event: OutboxEvent) -> str:
    if event.merge_key:
        return event.merge_key
    parts = [
        str(event.event_type),
        event.market_slug or "",
        event.condition_id or "",
        event.token_id or "",
    ]
    return "|".join(parts)


def _base_meta(event: OutboxEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    return {
        "event_id": event.event_id,
        "trace_id": event.trace_id,
        "event_type": str(event.event_type),
        "source_event_type": str(event.event_type),
        "source_event_id": event.event_id,
        "market_slug": event.market_slug,
        "condition_id": event.condition_id,
        "token_id": event.token_id,
        "reason": event.reason,
        "created_at": jsonable(event.created_at),
        "priority": event.priority,
        "retry_count": event.retry_count,
        "last_error": event.last_error,
        "idempotency_key": event.idempotency_key,
        "raw_payload": jsonable(payload),
    }


def _indexed_record(
    event: OutboxEvent,
    kind: str,
    index: int,
    data_key: str,
    item: Mapping[str, Any],
) -> dict[str, Any]:
    record = _base_meta(event)
    record.update(
        {
            "idempotency_key": _kind_idempotency_key(kind, event),
            f"{kind}_index": index,
            data_key: jsonable(item),
        }
    )
    record.update(jsonable(item))
    return record


def _kind_idempotency_key(kind: str, event: OutboxEvent) -> str:
    return f"{kind}:{event.idempotency_key}"


def _event_type_text(event: OutboxEvent) -> str:
    return str(event.event_type).strip()


def _first(payload: Mapping[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return value
    return None


def _mapping(payload: Mapping[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return None


def _mapping_list(payload: Mapping[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return [dict(value)]
        if isinstance(value, list):
            records = [dict(item) for item in value if isinstance(item, Mapping)]
            if records:
                return records
    return []
