from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from fdv_trader.app.reconcile_service import ReconcileAction, ReconcilePlan
from fdv_trader.app.strategy_service import StrategyService
from fdv_trader.app.trading_service import TradingReviewResult, TradingService
from fdv_trader.domain.allocation import Allocation
from fdv_trader.domain.events import AuditEvent, Fill
from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.domain.order import (
    Order,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    SellOrderIntent,
)
from fdv_trader.domain.orderbook import OrderbookSnapshot
from fdv_trader.domain.position import Position
from fdv_trader.infra.db import (
    AllocationRepository,
    AuditEventRepository,
    DatabasePersistenceRepository,
    FillRepository,
    MarketRepository,
    OrderRepository,
    PositionRepository,
    RepositoryPage,
)
from fdv_trader.runtime.account_state import AccountSnapshot
from fdv_trader.runtime.event_bus import EventBus, QueueDepthSnapshot
from fdv_trader.runtime.registry import MarketRegistrySnapshot


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal_text(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return str(value)


def _page_payload(page: RepositoryPage[Any], *, serializer: Callable[[Any], Any]) -> dict[str, Any]:
    return {
        "items": [serializer(item) for item in page.items],
        "total": page.total,
        "limit": page.limit,
        "offset": page.offset,
    }


def _market_status_allowed_for_manual_sell(market: Market) -> bool:
    return market.trading_status not in {
        TradingStatus.CLOSED,
        TradingStatus.RESOLVED,
        TradingStatus.REJECTED,
    }


def _order_status_is_terminal(order_status: OrderResultStatus) -> bool:
    return order_status in {
        OrderResultStatus.FULL_FILL,
        OrderResultStatus.PARTIAL_FILL,
        OrderResultStatus.NO_FILL,
        OrderResultStatus.REJECTED,
        OrderResultStatus.FAILED,
        OrderResultStatus.CANCELLED,
    }


def _order_result_to_order_status(result: OrderResult) -> OrderStatus:
    mapping = {
        OrderResultStatus.FULL_FILL: OrderStatus.MATCHED,
        OrderResultStatus.PARTIAL_FILL: OrderStatus.PARTIALLY_FILLED,
        OrderResultStatus.NO_FILL: OrderStatus.NO_FILL,
        OrderResultStatus.LIVE: OrderStatus.LIVE,
        OrderResultStatus.REJECTED: OrderStatus.REJECTED,
        OrderResultStatus.FAILED: OrderStatus.FAILED,
        OrderResultStatus.CANCELLED: OrderStatus.CANCELLED,
        OrderResultStatus.UNKNOWN_TIMEOUT: OrderStatus.FAILED,
    }
    return mapping.get(result.status, OrderStatus.FAILED)


def _normalize_condition_ids(condition_ids: Sequence[str] | None) -> tuple[str, ...]:
    if not condition_ids:
        return ()
    return tuple(condition_id for condition_id in condition_ids if condition_id)


@dataclass(frozen=True, slots=True)
class AdminService:
    """Coordinates read-only admin queries and controlled manual operations."""

    runtime: Any | None = None

    def bind_runtime(self, runtime: Any) -> "AdminService":
        return AdminService(runtime=runtime)

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "timestamp": _utc_now().isoformat(),
        }

    def readiness_snapshot(self) -> dict[str, Any]:
        config_readiness = self._config_readiness_snapshot()
        runtime_snapshot = self._runtime_status_snapshot()
        blocking_issues = self._runtime_blocking_issues(config_readiness, runtime_snapshot)
        ready_to_trade = bool(runtime_snapshot.get("ready_to_trade")) and not blocking_issues
        return {
            "ready_to_trade": ready_to_trade,
            "phase": runtime_snapshot["phase"],
            "blocking_issues": blocking_issues,
            "warnings": list(config_readiness.get("warnings", [])),
            "runtime": runtime_snapshot,
        }

    def runtime_snapshot(self) -> dict[str, Any]:
        runtime_status = self._runtime_status_snapshot()
        account = self._account_snapshot()
        registry = self._registry_snapshot()
        event_bus = self._event_bus_snapshot()
        persistence = self._persistence_snapshot()
        markets = [self._serialize_market_view(market) for market in registry.markets]
        return {
            "phase": runtime_status["phase"],
            "ready_to_trade": runtime_status["ready_to_trade"],
            "readiness": self._readiness_summary(),
            "settings": self._settings_snapshot(),
            "runtime": runtime_status,
            "bootstrap_summary": _jsonable(getattr(self.runtime, "bootstrap_summary", {})),
            "registry": {
                "market_count": len(registry.markets),
                "markets": [_jsonable(market) for market in markets],
            },
            "account": self._serialize_account_snapshot(account),
            "event_bus": _jsonable(event_bus) if event_bus is not None else None,
            "persistence": _jsonable(persistence) if persistence is not None else None,
            "markets": markets,
            "portfolio": self._portfolio_snapshot(account),
        }

    async def list_markets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trading_status: str | None = None,
    ) -> dict[str, Any]:
        if not self._has_db_session_factory():
            registry = self._registry_snapshot()
            account = self._account_snapshot()
            markets = tuple(
                market
                for market in registry.markets
                if trading_status is None or market.trading_status.value == trading_status
            )
            page = self._slice_sequence(markets, limit=limit, offset=offset)
            items = [
                self._serialize_market_view(
                    market,
                    account_snapshot=account,
                    registry_snapshot=registry,
                )
                for market in page.items
            ]
            return _page_payload(
                RepositoryPage(items=tuple(items), total=len(markets), limit=page.limit, offset=page.offset),
                serializer=lambda item: item,
            )

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.market.list_markets_snapshot(
                limit=limit,
                offset=offset,
                trading_status=trading_status,
            )

        page = await self._with_repositories(_query)
        registry = self._registry_snapshot()
        account = self._account_snapshot()
        items = [
            self._serialize_market_view(
                market,
                account_snapshot=account,
                registry_snapshot=registry,
            )
            for market in page.items
        ]
        return _page_payload(
            RepositoryPage(items=tuple(items), total=page.total, limit=page.limit, offset=page.offset),
            serializer=lambda item: item,
        )

    async def list_orders(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        open_only: bool = True,
        condition_id: str | None = None,
        token_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if open_only:
            snapshot = self._account_snapshot()
            orders = [
                order
                for order in snapshot.open_orders
                if (condition_id is None or order.condition_id == condition_id)
                and (token_id is None or order.token_id == token_id)
                and (trace_id is None or order.trace_id == trace_id)
            ]
            page = self._slice_sequence(orders, limit=limit, offset=offset)
            return _page_payload(page, serializer=self._serialize_order)

        if not self._has_db_session_factory():
            snapshot = self._account_snapshot()
            orders = [
                order
                for order in snapshot.open_orders
                if (condition_id is None or order.condition_id == condition_id)
                and (token_id is None or order.token_id == token_id)
                and (trace_id is None or order.trace_id == trace_id)
            ]
            page = self._slice_sequence(orders, limit=limit, offset=offset)
            return _page_payload(page, serializer=self._serialize_order)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.order.list_orders_snapshot(limit=limit, offset=offset, trace_id=trace_id)

        page = await self._with_repositories(_query)
        filtered_items = [
            order
            for order in page.items
            if (condition_id is None or order.condition_id == condition_id)
            and (token_id is None or order.token_id == token_id)
        ]
        return _page_payload(
            RepositoryPage(
                items=tuple(filtered_items),
                total=len(filtered_items),
                limit=page.limit,
                offset=page.offset,
            ),
            serializer=self._serialize_order,
        )

    async def list_fills(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        order_id: str | None = None,
        trade_id: str | None = None,
    ) -> dict[str, Any]:
        if not self._has_db_session_factory():
            snapshot = self._account_snapshot()
            fills = [
                fill
                for fill in snapshot.fills
                if (trace_id is None or fill.trace_id == trace_id)
                and (order_id is None or fill.order_id == order_id)
                and (trade_id is None or fill.trade_id == trade_id)
            ]
            page = self._slice_sequence(fills, limit=limit, offset=offset)
            return _page_payload(page, serializer=self._serialize_fill)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.fill.list_fills_snapshot(
                limit=limit,
                offset=offset,
                trace_id=trace_id,
                order_id=order_id,
                trade_id=trade_id,
            )

        page = await self._with_repositories(_query)
        return _page_payload(page, serializer=self._serialize_fill)

    async def list_positions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        condition_id: str | None = None,
        token_id: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        positions = [
            position
            for position in snapshot.positions
            if (condition_id is None or position.condition_id == condition_id)
            and (token_id is None or position.token_id == token_id)
        ]
        page = self._slice_sequence(positions, limit=limit, offset=offset)
        return _page_payload(page, serializer=self._serialize_position)

    async def list_audit_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        if not self._has_db_session_factory():
            page = RepositoryPage(items=tuple(), total=0, limit=limit, offset=offset)
            return _page_payload(page, serializer=self._serialize_audit_event)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.audit.list_audit_events_snapshot(
                limit=limit,
                offset=offset,
                trace_id=trace_id,
                event_type=event_type,
            )

        page = await self._with_repositories(_query)
        return _page_payload(page, serializer=self._serialize_audit_event)

    async def portfolio_snapshot(self) -> dict[str, Any]:
        account = self._account_snapshot()
        registry = self._registry_snapshot()
        if not self._has_db_session_factory():
            return {
                "balance_usdc": _decimal_text(account.balance_usdc),
                "allowance_usdc": _decimal_text(account.allowance_usdc),
                "available_usdc": _decimal_text(account.balance_usdc),
                "position_count": len(account.positions),
                "open_order_count": len(account.open_orders),
                "fill_count": len(account.fills),
                "pause_count": len(account.paused_markets),
                "last_reconcile_at": _jsonable(account.last_reconcile_at),
                "user_ws_connected": account.user_ws_connected,
                "allow_new_buys": account.allow_new_buys,
                "markets_tracked": len(registry.markets),
                "recent_allocations": [],
            }

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.allocation.list_allocations_snapshot(limit=50, offset=0)

        allocations = await self._with_repositories(_query)
        return {
            "balance_usdc": _decimal_text(account.balance_usdc),
            "allowance_usdc": _decimal_text(account.allowance_usdc),
            "available_usdc": _decimal_text(account.balance_usdc),
            "position_count": len(account.positions),
            "open_order_count": len(account.open_orders),
            "fill_count": len(account.fills),
            "pause_count": len(account.paused_markets),
            "last_reconcile_at": _jsonable(account.last_reconcile_at),
            "user_ws_connected": account.user_ws_connected,
            "allow_new_buys": account.allow_new_buys,
            "markets_tracked": len(registry.markets),
            "recent_allocations": [
                self._serialize_allocation(allocation) for allocation in allocations.items
            ],
        }

    async def reconcile(
        self,
        *,
        trace_id: str | None = None,
        condition_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        reconcile_worker = getattr(self.runtime, "reconcile_worker", None)
        if reconcile_worker is None:
            return {
                "status": "failed",
                "reason": "reconcile_worker_unavailable",
                "trace_id": trace_id or uuid4().hex,
            }
        condition_id_filter = _normalize_condition_ids(condition_ids)
        result = await reconcile_worker.reconcile_once(
            trace_id=trace_id,
            condition_ids=condition_id_filter or None,
        )
        return self._serialize_reconcile_result(result)

    async def cancel_replace_sell(
        self,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        new_price: Decimal,
        operator: str = "manual",
        reason: str = "admin_cancel_replace_sell",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        trace_id = trace_id or uuid4().hex
        market = self._resolve_market(
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
        )
        if market is None:
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "market_not_found",
            }
        if not _market_status_allowed_for_manual_sell(market):
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "market_not_operable",
                "market": self._serialize_market(market),
            }
        if new_price <= Decimal("0") or new_price >= Decimal("1"):
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "invalid_price",
                "market": self._serialize_market(market),
            }
        if market.tick_size <= Decimal("0"):
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "invalid_tick_size",
                "market": self._serialize_market(market),
            }
        tick_remainder = (new_price % market.tick_size) if market.tick_size else Decimal("0")
        if tick_remainder != Decimal("0"):
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "price_not_aligned_to_tick_size",
                "market": self._serialize_market(market),
                "new_price": _decimal_text(new_price),
            }

        account = self._account_snapshot()
        position = account.get_position(market.condition_id, market.no_token_id)
        if position is None or position.shares <= Decimal("0"):
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "no_position_to_sell",
                "market": self._serialize_market(market),
            }

        try:
            trading_service = self._trading_service()
            strategy_service = self._strategy_service()
        except RuntimeError as exc:
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": str(exc),
                "market": self._serialize_market(market),
            }
        open_sell_orders = account.open_sell_orders_for_market(market.condition_id, market.no_token_id)
        cancelled_orders: list[dict[str, Any]] = []
        failed_cancels: list[dict[str, Any]] = []

        for order in open_sell_orders:
            cancel_intent = strategy_service.build_cancel_intent(
                trace_id=trace_id,
                condition_id=market.condition_id,
                no_token_id=market.no_token_id,
                order_id=order.order_id or order.idempotency_key or f"{market.condition_id}:{market.no_token_id}:sell",
                market_slug=market.market_slug,
                reason=reason,
            )
            cancel_review = await trading_service.cancel(cancel_intent)
            cancelled_orders.append(self._serialize_review(cancel_review))
            cancel_result = cancel_review.order_result
            if cancel_result is None or not _order_status_is_terminal(cancel_result.status):
                failed_cancels.append(
                    {
                        "order": self._serialize_order(order),
                        "review": self._serialize_review(cancel_review),
                    }
                )
                break
            self._remove_hot_order(order)

        if failed_cancels:
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "cancel_failed",
                "market": self._serialize_market(market),
                "cancelled_orders": cancelled_orders,
                "failed_cancels": failed_cancels,
            }

        account = self._account_snapshot()
        sell_intent = SellOrderIntent(
            trace_id=trace_id,
            condition_id=market.condition_id,
            token_id=market.no_token_id,
            price=new_price,
            size_shares=position.shares,
            market_slug=market.market_slug,
        )
        sell_review = await trading_service.sell(
            sell_intent,
            market=market,
            position=position,
            open_orders=account.open_orders_for_market(market.condition_id, market.no_token_id),
            balance_usdc=account.balance_usdc,
            allowance_usdc=account.allowance_usdc,
            max_order_usdc=None,
            max_market_usdc=None,
            max_total_usdc=None,
            max_open_orders=None,
        )
        sell_result = sell_review.order_result
        if sell_result is None or sell_result.status == OrderResultStatus.FAILED:
            return {
                "status": "failed",
                "trace_id": trace_id,
                "reason": "replace_sell_failed",
                "market": self._serialize_market(market),
                "cancelled_orders": cancelled_orders,
                "replace_review": self._serialize_review(sell_review),
            }

        self._apply_hot_sell_result(market, sell_result, operator=operator, reason=reason)
        return {
            "status": "ok",
            "trace_id": trace_id,
            "operator": operator,
            "market": self._serialize_market(market),
            "cancelled_orders": cancelled_orders,
            "replace_review": self._serialize_review(sell_review),
            "replace_order_submitted": self._serialize_order_result(sell_result),
        }

    def _runtime_status_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else _jsonable(snapshot)
            readiness = payload.get("readiness") or {}
            user_ws = payload.get("user_ws") or {}
            account = payload.get("account") or {}
            return {
                "phase": payload.get("phase", "starting"),
                "ready_to_trade": bool(readiness.get("ready")),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "user_ws_connected": bool(user_ws.get("connected", account.get("user_ws_connected", False))),
                "allow_new_buys": bool(account.get("allow_new_buys", False)),
                "last_reconcile_at": readiness.get("last_reconcile_at") or account.get("last_reconcile_at"),
                "portfolio_budget_usdc": _decimal_text(getattr(self._settings(), "portfolio_budget_usdc", None)),
                "queue_depth": payload.get("queue_depths"),
                "persistence": payload.get("persistence"),
                "blocking_reasons": tuple(readiness.get("blocking_reasons", ())),
                "warnings": tuple(readiness.get("warnings", ())),
            }

        readiness = self._config_readiness_snapshot()
        account = self._account_snapshot()
        persistence = self._persistence_snapshot()
        event_bus = self._event_bus_snapshot()
        raw_low_priority_paused = getattr(event_bus, "low_priority_paused", False) if event_bus is not None else False
        low_priority_paused = bool(raw_low_priority_paused() if callable(raw_low_priority_paused) else raw_low_priority_paused)
        phase = "starting"
        ready_to_trade = bool(readiness.get("ready_to_trade"))
        if account.last_reconcile_at is None:
            phase = "recovering_snapshot"
        elif not account.user_ws_connected or not account.allow_new_buys:
            phase = "paused"
        elif persistence is not None and (
            getattr(persistence, "last_error", None) is not None
            or (getattr(persistence, "outbox_depth", 0) > 0 and low_priority_paused)
        ):
            phase = "degraded"
        elif ready_to_trade:
            phase = "trading_enabled"
        return {
            "phase": phase,
            "ready_to_trade": ready_to_trade and account.user_ws_connected and account.allow_new_buys,
            "user_ws_connected": account.user_ws_connected,
            "allow_new_buys": account.allow_new_buys,
            "last_reconcile_at": _jsonable(account.last_reconcile_at),
            "portfolio_budget_usdc": _decimal_text(getattr(self._settings(), "portfolio_budget_usdc", None)),
            "queue_depth": _jsonable(event_bus) if event_bus is not None else None,
            "persistence": _jsonable(persistence) if persistence is not None else None,
        }

    def _config_readiness_snapshot(self) -> dict[str, Any]:
        settings = getattr(self.runtime, "readiness", None)
        if settings is not None:
            return settings.as_dict()
        return {
            "ready_to_trade": False,
            "blocking_issues": [],
            "warnings": [],
        }

    def _runtime_blocking_issues(
        self,
        config_readiness: dict[str, Any],
        runtime_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        blocking_issues = list(config_readiness.get("blocking_issues", []))
        blocking_reasons = runtime_snapshot.get("blocking_reasons", ())
        if blocking_reasons:
            blocking_issues.extend(
                {
                    "field": "runtime",
                    "code": "runtime_blocked",
                    "message": str(reason),
                }
                for reason in blocking_reasons
            )
        if not runtime_snapshot["user_ws_connected"]:
            blocking_issues.append(
                {
                    "field": "user_ws_connected",
                    "code": "ws_disconnected",
                    "message": "User WS 未连接，暂停自动下单",
                }
            )
        if not runtime_snapshot["allow_new_buys"]:
            blocking_issues.append(
                {
                    "field": "allow_new_buys",
                    "code": "buy_gate_closed",
                    "message": "自动买入闸门关闭",
                }
            )
        if runtime_snapshot["last_reconcile_at"] is None:
            blocking_issues.append(
                {
                    "field": "last_reconcile_at",
                    "code": "reconcile_pending",
                    "message": "首次 reconcile 未完成，禁止自动下单",
                }
            )
        return blocking_issues

    def _readiness_summary(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            readiness = snapshot.readiness
            if readiness is not None:
                return readiness.as_dict() if hasattr(readiness, "as_dict") else _jsonable(readiness)
        config_readiness = self._config_readiness_snapshot()
        runtime_snapshot = self._runtime_status_snapshot()
        blocking_issues = self._runtime_blocking_issues(config_readiness, runtime_snapshot)
        return {
            "ready_to_trade": bool(config_readiness.get("ready_to_trade")) and not blocking_issues,
            "phase": runtime_snapshot["phase"],
            "blocking_issues": blocking_issues,
            "warnings": list(config_readiness.get("warnings", [])),
        }

    def _settings_snapshot(self) -> dict[str, Any]:
        settings = self._settings()
        if settings is None:
            return {}
        if hasattr(settings, "sanitized_dump"):
            return settings.sanitized_dump()
        return _jsonable(settings)

    def _portfolio_snapshot(self, account: AccountSnapshot) -> dict[str, Any]:
        return {
            "balance_usdc": _decimal_text(account.balance_usdc),
            "allowance_usdc": _decimal_text(account.allowance_usdc),
            "positions": len(account.positions),
            "open_orders": len(account.open_orders),
            "fills": len(account.fills),
            "paused_markets": list(account.paused_markets),
            "pause_reasons": [list(item) for item in account.pause_reasons],
            "allow_new_buys": account.allow_new_buys,
            "user_ws_connected": account.user_ws_connected,
            "last_reconcile_at": _jsonable(account.last_reconcile_at),
        }

    def _serialize_account_snapshot(self, account: AccountSnapshot) -> dict[str, Any]:
        return {
            "balance_usdc": _decimal_text(account.balance_usdc),
            "allowance_usdc": _decimal_text(account.allowance_usdc),
            "positions": [_jsonable(position) for position in account.positions],
            "open_orders": [_jsonable(order) for order in account.open_orders],
            "fills": [_jsonable(fill) for fill in account.fills],
            "user_ws_connected": account.user_ws_connected,
            "allow_new_buys": account.allow_new_buys,
            "paused_markets": list(account.paused_markets),
            "pause_reasons": [list(item) for item in account.pause_reasons],
            "last_reconcile_at": _jsonable(account.last_reconcile_at),
        }

    def _serialize_market_view(
        self,
        market: Market,
        *,
        account_snapshot: AccountSnapshot | None = None,
        registry_snapshot: MarketRegistrySnapshot | None = None,
    ) -> dict[str, Any]:
        if account_snapshot is None:
            account_snapshot = self._account_snapshot()
        if registry_snapshot is None:
            registry_snapshot = self._registry_snapshot()
        orderbook = self._market_ws_snapshot(market.no_token_id)
        position = account_snapshot.get_position(market.condition_id, market.no_token_id)
        open_orders = account_snapshot.open_orders_for_market(market.condition_id, market.no_token_id)
        return {
            "market": self._serialize_market(market),
            "tracked": registry_snapshot.get_by_condition_id(market.condition_id) is not None,
            "orderbook": self._serialize_orderbook(orderbook),
            "position": self._serialize_position(position) if position is not None else None,
            "open_orders": [self._serialize_order(order) for order in open_orders],
            "open_order_count": len(open_orders),
            "best_ask": _decimal_text(orderbook.best_ask) if orderbook is not None else None,
            "best_bid": _decimal_text(orderbook.best_bid) if orderbook is not None else None,
            "spread": _decimal_text(orderbook.spread) if orderbook is not None else None,
            "entry_price_touched": bool(
                orderbook is not None and orderbook.no_entry_touched(Decimal("0.60"))
            ),
        }

    def _serialize_market(self, market: Market) -> dict[str, Any]:
        return {
            "condition_id": market.condition_id,
            "market_slug": market.market_slug,
            "event_slug": market.event_slug,
            "event_id": market.event_id,
            "event_title": market.event_title,
            "no_token_id": market.no_token_id,
            "yes_token_id": market.yes_token_id,
            "tick_size": _decimal_text(market.tick_size),
            "min_order_size": _decimal_text(market.min_order_size),
            "neg_risk": market.neg_risk,
            "category": market.category,
            "tags": list(market.tags),
            "matched_keywords": list(market.matched_keywords),
            "trading_status": market.trading_status.value,
            "reject_reason": market.reject_reason,
        }

    def _serialize_orderbook(self, orderbook: OrderbookSnapshot | None) -> dict[str, Any] | None:
        if orderbook is None:
            return None
        return {
            "token_id": orderbook.token_id,
            "condition_id": orderbook.condition_id,
            "market_slug": orderbook.market_slug,
            "best_bid": _decimal_text(orderbook.best_bid),
            "best_ask": _decimal_text(orderbook.best_ask),
            "best_bid_size": _decimal_text(orderbook.best_bid_size),
            "best_ask_size": _decimal_text(orderbook.best_ask_size),
            "last_trade_price": _decimal_text(orderbook.last_trade_price),
            "tick_size": _decimal_text(orderbook.tick_size),
            "spread": _decimal_text(orderbook.spread),
            "received_at": _jsonable(orderbook.received_at),
            "bids": [{"price": _decimal_text(level.price), "size": _decimal_text(level.size)} for level in orderbook.bids],
            "asks": [{"price": _decimal_text(level.price), "size": _decimal_text(level.size)} for level in orderbook.asks],
        }

    def _serialize_position(self, position: Position) -> dict[str, Any]:
        return {
            "condition_id": position.condition_id,
            "token_id": position.token_id,
            "market_slug": position.market_slug,
            "shares": _decimal_text(position.shares),
            "cost_usdc": _decimal_text(position.cost_usdc),
            "open_buy_shares": _decimal_text(position.open_buy_shares),
            "open_sell_shares": _decimal_text(position.open_sell_shares),
            "pending_buy_shares": _decimal_text(position.pending_buy_shares),
            "confirmed_shares": _decimal_text(position.confirmed_shares),
            "last_order_id": position.last_order_id,
            "last_trade_id": position.last_trade_id,
            "confirmation_status": position.confirmation_status,
            "updated_at": _jsonable(position.updated_at),
        }

    def _serialize_order(self, order: Order) -> dict[str, Any]:
        return {
            "trace_id": order.trace_id,
            "condition_id": order.condition_id,
            "token_id": order.token_id,
            "market_slug": order.market_slug,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "price": _decimal_text(order.price),
            "amount_usdc": _decimal_text(order.amount_usdc),
            "size_shares": _decimal_text(order.size_shares),
            "filled_shares": _decimal_text(order.filled_shares),
            "remaining_shares": _decimal_text(order.remaining_shares),
            "notional_usdc": _decimal_text(order.notional_usdc),
            "order_id": order.order_id,
            "trade_id": order.trade_id,
            "status": order.status.value,
            "idempotency_key": order.idempotency_key,
            "reason": order.reason,
            "post_only": order.post_only,
            "created_at": _jsonable(order.created_at),
            "updated_at": _jsonable(order.updated_at),
        }

    def _serialize_fill(self, fill: Fill) -> dict[str, Any]:
        return {
            "trace_id": fill.trace_id,
            "event_type": str(fill.event_type),
            "event_id": fill.event_id,
            "market_slug": fill.market_slug,
            "condition_id": fill.condition_id,
            "token_id": fill.token_id,
            "reason": fill.reason,
            "created_at": _jsonable(fill.created_at),
            "order_id": fill.order_id,
            "trade_id": fill.trade_id,
            "side": fill.side,
            "price": _decimal_text(fill.price),
            "size": _decimal_text(fill.size),
            "notional_usdc": _decimal_text(fill.notional_usdc),
            "status": fill.status,
            "confirmed_at": _jsonable(fill.confirmed_at),
        }

    def _serialize_audit_event(self, event: AuditEvent) -> dict[str, Any]:
        return {
            "trace_id": event.trace_id,
            "event_id": event.event_id,
            "event_title": event.event_title,
            "market_slug": event.market_slug,
            "condition_id": event.condition_id,
            "token_id": event.token_id,
            "outcome": event.outcome,
            "side": event.side,
            "order_type": event.order_type,
            "price": _jsonable(event.price),
            "size": _jsonable(event.size),
            "notional_usdc": _jsonable(event.notional_usdc),
            "order_id": event.order_id,
            "trade_id": event.trade_id,
            "tx_hash": event.tx_hash,
            "status": event.status,
            "reason": event.reason,
            "raw_response": event.raw_response,
            "created_at": _jsonable(event.created_at),
            "updated_at": _jsonable(event.updated_at),
        }

    def _serialize_allocation(self, allocation: Allocation) -> dict[str, Any]:
        return {
            "condition_id": allocation.condition_id,
            "market_slug": allocation.market_slug,
            "token_id": allocation.token_id,
            "target_budget_usdc": _decimal_text(allocation.target_budget_usdc),
            "buy_budget_usdc": _decimal_text(allocation.buy_budget_usdc),
            "current_exposure_usdc": _decimal_text(allocation.current_exposure_usdc),
            "released_budget_usdc": _decimal_text(allocation.released_budget_usdc),
            "reason": allocation.reason,
            "release_reason": allocation.release_reason,
            "idempotency_key": allocation.idempotency_key,
        }

    def _serialize_review(self, review: TradingReviewResult) -> dict[str, Any]:
        return {
            "operation": review.operation,
            "submitted": review.submitted,
            "risk_decision": None
            if review.risk_decision is None
            else {
                "passed": review.risk_decision.passed,
                "reason": review.risk_decision.reason,
                "retryable": review.risk_decision.retryable,
            },
            "order_result": self._serialize_order_result(review.order_result),
            "submission_error": review.submission_error,
        }

    def _serialize_order_result(self, result: OrderResult | None) -> dict[str, Any] | None:
        if result is None:
            return None
        return {
            "trace_id": result.trace_id,
            "condition_id": result.condition_id,
            "token_id": result.token_id,
            "market_slug": result.market_slug,
            "status": result.status.value,
            "order_id": result.order_id,
            "trade_id": result.trade_id,
            "side": None if result.side is None else result.side.value,
            "order_type": None if result.order_type is None else result.order_type.value,
            "price": _decimal_text(result.price),
            "requested_amount_usdc": _decimal_text(result.requested_amount_usdc),
            "requested_size_shares": _decimal_text(result.requested_size_shares),
            "matched_shares": _decimal_text(result.matched_shares),
            "remaining_shares": _decimal_text(result.remaining_shares),
            "spent_usdc": _decimal_text(result.spent_usdc),
            "notional_usdc": _decimal_text(result.notional_usdc),
            "reason": result.reason,
            "retryable": result.retryable,
            "raw_response_summary": result.raw_response_summary,
            "timestamps": _jsonable(result.timestamps),
        }

    def _serialize_reconcile_result(self, result: Any) -> dict[str, Any]:
        plan: ReconcilePlan = result.plan
        return {
            "trace_id": result.trace_id,
            "status": "ok",
            "plan": {
                "trace_id": plan.trace_id,
                "generated_at": _jsonable(plan.generated_at),
                "total_actions": plan.total_actions,
                "paused_markets": plan.paused_markets,
                "diff_count": plan.diff_count,
                "has_changes": plan.has_changes,
                "market_plans": [
                    {
                        "trace_id": market_plan.trace_id,
                        "market": self._serialize_market(market_plan.market),
                        "actions": [self._serialize_reconcile_action(action) for action in market_plan.actions],
                        "pause_trading": market_plan.pause_trading,
                        "pause_reason": market_plan.pause_reason,
                    }
                    for market_plan in plan.market_plans
                ],
            },
            "applied_actions": [self._serialize_reconcile_action(action) for action in result.applied_actions],
            "failed_actions": [
                {
                    "action": self._serialize_reconcile_action(action),
                    "reason": reason,
                }
                for action, reason in result.failed_actions
            ],
        }

    def _serialize_reconcile_action(self, action: ReconcileAction) -> dict[str, Any]:
        return {
            "action_type": action.action_type.value,
            "trace_id": action.trace_id,
            "condition_id": action.condition_id,
            "token_id": action.token_id,
            "market_slug": action.market_slug,
            "reason": action.reason,
            "source_order_id": action.source_order_id,
            "source_order_side": None if action.source_order_side is None else action.source_order_side.value,
            "target_size_shares": _decimal_text(action.target_size_shares),
            "target_notional_usdc": _decimal_text(action.target_notional_usdc),
            "pause_reason": action.pause_reason,
        }

    def _account_snapshot(self) -> AccountSnapshot:
        account_state = getattr(self.runtime, "account_state_store", None)
        if account_state is not None:
            return account_state.snapshot()
        return AccountSnapshot()

    def _registry_snapshot(self) -> MarketRegistrySnapshot:
        registry = getattr(self.runtime, "registry", None)
        if registry is not None:
            return registry.snapshot()
        return MarketRegistrySnapshot(tuple())

    def _event_bus_snapshot(self) -> QueueDepthSnapshot | None:
        event_bus = getattr(self.runtime, "event_bus", None)
        if event_bus is None:
            return None
        return event_bus.snapshot()

    def _persistence_snapshot(self) -> Any | None:
        worker = getattr(self.runtime, "persistence_worker", None)
        if worker is None:
            return None
        snapshot = worker.snapshot()
        return snapshot

    def _has_db_session_factory(self) -> bool:
        return getattr(self.runtime, "db_session_factory", None) is not None

    def _market_ws_snapshot(self, token_id: str) -> OrderbookSnapshot | None:
        worker = getattr(self.runtime, "market_ws_worker", None)
        if worker is None:
            return None
        return worker.snapshot(token_id)

    def _settings(self) -> Any | None:
        return getattr(self.runtime, "settings", None)

    def _trading_service(self) -> TradingService:
        trading_service = getattr(self.runtime, "trading_service", None)
        if trading_service is None:
            raise RuntimeError("trading_service unavailable")
        return trading_service

    def _strategy_service(self) -> StrategyService:
        strategy_service = getattr(self.runtime, "strategy_service", None)
        if strategy_service is None:
            raise RuntimeError("strategy_service unavailable")
        return strategy_service

    def _resolve_market(
        self,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
    ) -> Market | None:
        registry = getattr(self.runtime, "registry", None)
        if registry is not None:
            if condition_id is not None:
                market = registry.get_by_condition_id(condition_id)
                if market is not None:
                    return market
            if token_id is not None:
                market = registry.get_by_no_token_id(token_id)
                if market is not None:
                    return market
            if market_slug is not None:
                market = registry.get_by_slug(market_slug)
                if market is not None:
                    return market
        return None

    async def _with_repositories(self, callback: Callable[[_RepositoryGroup], Any]) -> Any:
        session_factory = getattr(self.runtime, "db_session_factory", None)
        if session_factory is None:
            raise RuntimeError("db_session_factory unavailable")
        async with session_factory() as session:
            repositories = _RepositoryGroup(
                audit=AuditEventRepository(session),
                market=MarketRepository(session),
                order=OrderRepository(session),
                fill=FillRepository(session),
                position=PositionRepository(session),
                allocation=AllocationRepository(session),
            )
            return await callback(repositories)

    def _slice_sequence(
        self,
        items: Sequence[Any],
        *,
        limit: int,
        offset: int,
    ) -> RepositoryPage[Any]:
        if limit <= 0:
            limit = 100
        if offset < 0:
            offset = 0
        sliced = tuple(items[offset : offset + limit])
        return RepositoryPage(items=sliced, total=len(items), limit=limit, offset=offset)

    def _remove_hot_order(self, order: Order) -> None:
        account_state = getattr(self.runtime, "account_state_store", None)
        if account_state is None:
            return
        order_id = order.order_id or order.idempotency_key or f"{order.condition_id}:{order.token_id}:{order.side.value}"
        account_state.remove_order(order_id)

    def _apply_hot_sell_result(
        self,
        market: Market,
        result: OrderResult,
        *,
        operator: str,
        reason: str,
    ) -> None:
        account_state = getattr(self.runtime, "account_state_store", None)
        if account_state is None:
            return
        open_sell_shares = result.remaining_shares
        if result.status == OrderResultStatus.LIVE and open_sell_shares <= Decimal("0"):
            open_sell_shares = result.requested_size_shares or Decimal("0")
        if open_sell_shares < Decimal("0"):
            open_sell_shares = Decimal("0")
        order_id = result.order_id or result.trace_id
        account_state.upsert_order(
            Order(
                trace_id=result.trace_id,
                condition_id=result.condition_id,
                token_id=result.token_id,
                market_slug=market.market_slug,
                side=OrderSide.SELL,
                order_type=OrderType.GTC,
                price=result.price or Decimal("0"),
                size_shares=result.requested_size_shares,
                filled_shares=result.matched_shares,
                remaining_shares=open_sell_shares,
                notional_usdc=result.notional_usdc,
                order_id=order_id,
                trade_id=result.trade_id,
                status=_order_result_to_order_status(result),
                idempotency_key=result.intent.idempotency_key if result.intent is not None else order_id,
                reason=f"{reason}:{operator}",
                post_only=bool(getattr(result.intent, "post_only", False)),
                created_at=result.timestamps.queued_at,
                updated_at=result.timestamps.ack_at,
            )
        )
        position = account_state.snapshot().get_position(market.condition_id, market.no_token_id)
        if position is not None:
            account_state.upsert_position(
                Position(
                    condition_id=position.condition_id,
                    token_id=position.token_id,
                    shares=position.shares,
                    cost_usdc=position.cost_usdc,
                    market_slug=position.market_slug or market.market_slug,
                    open_buy_shares=position.open_buy_shares,
                    open_sell_shares=open_sell_shares,
                    pending_buy_shares=position.pending_buy_shares,
                    confirmed_shares=position.confirmed_shares,
                    last_order_id=order_id,
                    last_trade_id=result.trade_id,
                    confirmation_status=_order_status_to_text(result.status),
                    updated_at=result.timestamps.ack_at,
                )
            )


@dataclass(frozen=True, slots=True)
class _RepositoryGroup:
    audit: AuditEventRepository
    market: MarketRepository
    order: OrderRepository
    fill: FillRepository
    position: PositionRepository
    allocation: AllocationRepository


def _order_status_to_text(status: OrderResultStatus) -> str:
    return {
        OrderResultStatus.FULL_FILL: "full_fill",
        OrderResultStatus.PARTIAL_FILL: "partial_fill",
        OrderResultStatus.NO_FILL: "no_fill",
        OrderResultStatus.LIVE: "live",
        OrderResultStatus.REJECTED: "rejected",
        OrderResultStatus.FAILED: "failed",
        OrderResultStatus.CANCELLED: "cancelled",
        OrderResultStatus.UNKNOWN_TIMEOUT: "unknown_timeout",
    }.get(status, "unknown")
