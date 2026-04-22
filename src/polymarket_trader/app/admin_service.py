from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal, Mapping, Sequence
from uuid import uuid4

from polymarket_trader.app.admin_operations import (
    normalize_condition_ids,
)
from polymarket_trader.app.admin_order_control import AdminOrderController
from polymarket_trader.app.admin_serialization import AdminSerializer, decimal_text, jsonable, page_payload
from polymarket_trader.app.order_projection import normalize_order_id
from polymarket_trader.app.trading_service import TradingService
from polymarket_trader.domain.market import Market
from polymarket_trader.domain.order import Order
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.infra.db import (
    AllocationRepository,
    AuditEventRepository,
    FillRepository,
    MarketRepository,
    OrderRepository,
    OutboxEventRepository,
    PositionRepository,
    RepositoryPage,
)
from polymarket_trader.domain.account import AccountSnapshot
from polymarket_trader.runtime.event_bus import QueueDepthSnapshot
from polymarket_trader.runtime.registry import MarketRegistrySnapshot
from polymarket_trader.serialization import utc_now


MarketFeeSortField = Literal[
    "market_slug",
    "fee_rate_bps",
    "fee_rate_updated_at",
    "maker_base_fee_bps",
    "taker_base_fee_bps",
]
SortDirection = Literal["asc", "desc"]


def _market_matches_fee_filters(
    market: Market,
    *,
    fees_enabled: bool | None = None,
    fee_rate_bps_min: int | None = None,
    fee_rate_bps_max: int | None = None,
    maker_base_fee_bps_min: int | None = None,
    maker_base_fee_bps_max: int | None = None,
    taker_base_fee_bps_min: int | None = None,
    taker_base_fee_bps_max: int | None = None,
) -> bool:
    if fees_enabled is not None and market.fees_enabled is not fees_enabled:
        return False
    if fee_rate_bps_min is not None and (market.fee_rate_bps is None or market.fee_rate_bps < fee_rate_bps_min):
        return False
    if fee_rate_bps_max is not None and (market.fee_rate_bps is None or market.fee_rate_bps > fee_rate_bps_max):
        return False
    if maker_base_fee_bps_min is not None and (
        market.maker_base_fee_bps is None or market.maker_base_fee_bps < maker_base_fee_bps_min
    ):
        return False
    if maker_base_fee_bps_max is not None and (
        market.maker_base_fee_bps is None or market.maker_base_fee_bps > maker_base_fee_bps_max
    ):
        return False
    if taker_base_fee_bps_min is not None and (
        market.taker_base_fee_bps is None or market.taker_base_fee_bps < taker_base_fee_bps_min
    ):
        return False
    if taker_base_fee_bps_max is not None and (
        market.taker_base_fee_bps is None or market.taker_base_fee_bps > taker_base_fee_bps_max
    ):
        return False
    return True


def _market_sort_value(market: Market, sort_by: MarketFeeSortField) -> object | None:
    return {
        "market_slug": market.market_slug,
        "fee_rate_bps": market.fee_rate_bps,
        "fee_rate_updated_at": market.fee_rate_updated_at,
        "maker_base_fee_bps": market.maker_base_fee_bps,
        "taker_base_fee_bps": market.taker_base_fee_bps,
    }[sort_by]


def _sort_markets(
    markets: Sequence[Market],
    *,
    sort_by: MarketFeeSortField | None = None,
    sort_direction: SortDirection = "desc",
) -> tuple[Market, ...]:
    if sort_by is None:
        return tuple(markets)
    present = [market for market in markets if _market_sort_value(market, sort_by) is not None]
    missing = [market for market in markets if _market_sort_value(market, sort_by) is None]
    present.sort(
        key=lambda market: _market_sort_value(market, sort_by),
        reverse=sort_direction == "desc",
    )
    return tuple(present + missing)


@dataclass(frozen=True, slots=True)
class AdminService:
    """Coordinates read-only admin queries and controlled manual operations."""

    runtime: Any | None = None

    def bind_runtime(self, runtime: Any) -> "AdminService":
        return AdminService(runtime=runtime)

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "timestamp": utc_now().isoformat(),
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
        market_discovery = self._market_discovery_snapshot()
        event_bus = self._event_bus_snapshot()
        persistence = self._persistence_snapshot()
        markets = [self._serializer().market_view(market) for market in registry.markets]
        return {
            "phase": runtime_status["phase"],
            "ready_to_trade": runtime_status["ready_to_trade"],
            "readiness": self._readiness_summary(),
            "settings": self._settings_snapshot(),
            "identity": self._identity_snapshot(),
            "runtime": runtime_status,
            "bootstrap_summary": jsonable(getattr(self.runtime, "bootstrap_summary", {})),
            "market_discovery": market_discovery,
            "registry": {
                "market_count": len(registry.markets),
                "markets": [jsonable(market) for market in markets],
            },
            "account": self._serializer().account_snapshot(account),
            "event_bus": jsonable(event_bus) if event_bus is not None else None,
            "persistence": jsonable(persistence) if persistence is not None else None,
            "markets": markets,
            "portfolio": self._serializer().portfolio_snapshot(account),
        }

    async def list_markets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trading_status: str | None = None,
        fees_enabled: bool | None = None,
        fee_rate_bps_min: int | None = None,
        fee_rate_bps_max: int | None = None,
        maker_base_fee_bps_min: int | None = None,
        maker_base_fee_bps_max: int | None = None,
        taker_base_fee_bps_min: int | None = None,
        taker_base_fee_bps_max: int | None = None,
        sort_by: MarketFeeSortField | None = None,
        sort_direction: SortDirection = "desc",
    ) -> dict[str, Any]:
        registry = self._registry_snapshot()
        if registry.markets or not self._has_db_session_factory():
            account = self._account_snapshot()
            markets = _sort_markets(
                tuple(
                    market
                    for market in registry.markets
                    if (trading_status is None or market.trading_status.value == trading_status)
                    and _market_matches_fee_filters(
                        market,
                        fees_enabled=fees_enabled,
                        fee_rate_bps_min=fee_rate_bps_min,
                        fee_rate_bps_max=fee_rate_bps_max,
                        maker_base_fee_bps_min=maker_base_fee_bps_min,
                        maker_base_fee_bps_max=maker_base_fee_bps_max,
                        taker_base_fee_bps_min=taker_base_fee_bps_min,
                        taker_base_fee_bps_max=taker_base_fee_bps_max,
                    )
                ),
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            page = self._slice_sequence(markets, limit=limit, offset=offset)
            items = [
                self._serializer().market_view(
                    market,
                    account_snapshot=account,
                    registry_snapshot=registry,
                )
                for market in page.items
            ]
            return page_payload(
                RepositoryPage(items=tuple(items), total=len(markets), limit=page.limit, offset=page.offset),
                serializer=lambda item: item,
            )

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.market.list_markets_snapshot(
                limit=limit,
                offset=offset,
                trading_status=trading_status,
                fees_enabled=fees_enabled,
                fee_rate_bps_min=fee_rate_bps_min,
                fee_rate_bps_max=fee_rate_bps_max,
                maker_base_fee_bps_min=maker_base_fee_bps_min,
                maker_base_fee_bps_max=maker_base_fee_bps_max,
                taker_base_fee_bps_min=taker_base_fee_bps_min,
                taker_base_fee_bps_max=taker_base_fee_bps_max,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )

        page = await self._with_repositories(_query)
        registry = self._registry_snapshot()
        account = self._account_snapshot()
        items = [
            self._serializer().market_view(
                market,
                account_snapshot=account,
                registry_snapshot=registry,
            )
            for market in page.items
        ]
        return page_payload(
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
        order_id: str | None = None,
        trade_id: str | None = None,
    ) -> dict[str, Any]:
        if open_only:
            snapshot = self._account_snapshot()
            orders = [
                order
                for order in snapshot.open_orders
                if (condition_id is None or order.condition_id == condition_id)
                and (token_id is None or order.token_id == token_id)
                and (trace_id is None or order.trace_id == trace_id)
                and (order_id is None or order.order_id == order_id)
                and (trade_id is None or order.trade_id == trade_id)
            ]
            page = self._slice_sequence(orders, limit=limit, offset=offset)
            return page_payload(page, serializer=self._serializer().order)

        if not self._has_db_session_factory():
            snapshot = self._account_snapshot()
            orders = [
                order
                for order in snapshot.open_orders
                if (condition_id is None or order.condition_id == condition_id)
                and (token_id is None or order.token_id == token_id)
                and (trace_id is None or order.trace_id == trace_id)
                and (order_id is None or order.order_id == order_id)
                and (trade_id is None or order.trade_id == trade_id)
            ]
            page = self._slice_sequence(orders, limit=limit, offset=offset)
            return page_payload(page, serializer=self._serializer().order)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.order.list_orders_snapshot(
                limit=limit,
                offset=offset,
                trace_id=trace_id,
                order_id=order_id,
                trade_id=trade_id,
                condition_id=condition_id,
                token_id=token_id,
            )

        page = await self._with_repositories(_query)
        return page_payload(page, serializer=self._serializer().order)

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
            return page_payload(page, serializer=self._serializer().fill)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.fill.list_fills_snapshot(
                limit=limit,
                offset=offset,
                trace_id=trace_id,
                order_id=order_id,
                trade_id=trade_id,
            )

        page = await self._with_repositories(_query)
        return page_payload(page, serializer=self._serializer().fill)

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
        return page_payload(page, serializer=self._serializer().position)

    async def get_market(
        self,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
    ) -> dict[str, Any] | None:
        market = self._resolve_market(
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
        )
        if market is None and self._has_db_session_factory():
            async def _query(repos: _RepositoryGroup) -> Market | None:
                if condition_id is not None:
                    market_by_condition = await repos.market.get_by_condition_id(condition_id)
                    if market_by_condition is not None:
                        return market_by_condition
                if token_id is not None:
                    market_by_token = await repos.market.get_by_token_id(token_id)
                    if market_by_token is not None:
                        return market_by_token
                if market_slug is not None:
                    return await repos.market.get_by_market_slug(market_slug)
                return None

            market = await self._with_repositories(_query)
        if market is None:
            return None
        return self._serializer().market_view(market)

    async def get_market_orderbook(
        self,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
    ) -> dict[str, Any] | None:
        market = self._resolve_market(
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
        )
        resolved_market_slug = market.market_slug if market is not None else market_slug
        resolved_condition_id = market.condition_id if market is not None else condition_id
        resolved_token_id = token_id
        if resolved_token_id is None:
            return None

        snapshot = self._market_ws_snapshot(resolved_token_id)
        source = "hot"
        if snapshot is None:
            orderbook = await self._clob_client().get_orderbook(
                resolved_token_id,
                market_slug=resolved_market_slug,
                condition_id=resolved_condition_id,
            )
            snapshot = orderbook.to_snapshot()
            source = "rest"
        return self._serializer().market_orderbook(
            token_id=resolved_token_id,
            condition_id=resolved_condition_id,
            market_slug=resolved_market_slug,
            orderbook=snapshot,
            source=source,
        )

    async def get_market_midpoint(
        self,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
    ) -> dict[str, Any] | None:
        market = self._resolve_market(
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
        )
        resolved_market_slug = market.market_slug if market is not None else market_slug
        resolved_condition_id = market.condition_id if market is not None else condition_id
        resolved_token_id = token_id
        if resolved_token_id is None:
            return None

        snapshot = self._market_ws_snapshot(resolved_token_id)
        source = "hot"
        if snapshot is not None and snapshot.best_bid is not None and snapshot.best_ask is not None:
            midpoint = (snapshot.best_bid + snapshot.best_ask) / Decimal("2")
        else:
            midpoint = await self._clob_client().get_midpoint(resolved_token_id)
            source = "rest"
        return self._serializer().market_midpoint(
            token_id=resolved_token_id,
            condition_id=resolved_condition_id,
            market_slug=resolved_market_slug,
            midpoint=midpoint,
            orderbook=snapshot,
            source=source,
        )

    async def get_market_prices_history(
        self,
        *,
        token_id: str,
        start_ts: int | None = None,
        end_ts: int | None = None,
        interval: str | None = None,
        fidelity: int | None = None,
    ) -> dict[str, Any]:
        history = await self._clob_client().get_prices_history(
            token_id,
            start_ts=start_ts,
            end_ts=end_ts,
            interval=interval,
            fidelity=fidelity,
        )
        return self._serializer().market_prices_history(
            token_id=token_id,
            history=history,
            interval=interval,
            fidelity=fidelity,
        )

    async def list_audit_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        event_title: str | None = None,
    ) -> dict[str, Any]:
        if not self._has_db_session_factory():
            page = RepositoryPage(items=tuple(), total=0, limit=limit, offset=offset)
            return page_payload(page, serializer=self._serializer().audit_event)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.audit.list_audit_events_snapshot(
                limit=limit,
                offset=offset,
                trace_id=trace_id,
                event_title=event_title,
            )

        page = await self._with_repositories(_query)
        return page_payload(page, serializer=self._serializer().audit_event)

    async def list_allocations(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        market_slug: str | None = None,
    ) -> dict[str, Any]:
        if not self._has_db_session_factory():
            page = RepositoryPage(items=tuple(), total=0, limit=limit, offset=offset)
            return page_payload(page, serializer=self._serializer().allocation)

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.allocation.list_allocations_snapshot(
                limit=limit,
                offset=offset,
                trace_id=trace_id,
                condition_id=condition_id,
                token_id=token_id,
                market_slug=market_slug,
            )

        page = await self._with_repositories(_query)
        return page_payload(page, serializer=self._serializer().allocation)

    async def list_outbox_pending(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        runtime_outbox = getattr(self.runtime, "outbox", None)
        if runtime_outbox is not None and hasattr(runtime_outbox, "pending_events"):
            events = runtime_outbox.pending_events()
            if trace_id is not None:
                events = tuple(event for event in events if event.trace_id == trace_id)
            page = RepositoryPage(
                items=tuple(events[offset : offset + limit]),
                total=len(events),
                limit=limit,
                offset=offset,
            )
            return page_payload(page, serializer=self._serializer().outbox_event)

        page = RepositoryPage(items=tuple(), total=0, limit=limit, offset=offset)
        return page_payload(page, serializer=self._serializer().outbox_event)

    async def portfolio_snapshot(self) -> dict[str, Any]:
        account = self._account_snapshot()
        registry = self._registry_snapshot()
        if not self._has_db_session_factory():
            return {
                "balance_usdc": decimal_text(account.balance_usdc),
                "allowance_usdc": decimal_text(account.allowance_usdc),
                "available_usdc": decimal_text(account.balance_usdc),
                "position_count": len(account.positions),
                "open_order_count": len(account.open_orders),
                "fill_count": len(account.fills),
                "pause_count": len(account.paused_markets),
                "last_reconcile_at": jsonable(account.last_reconcile_at),
                "user_ws_connected": account.user_ws_connected,
                "allow_new_entries": account.allow_new_entries,
                "markets_tracked": len(registry.markets),
                "recent_allocations": [],
            }

        async def _query(repos: _RepositoryGroup) -> RepositoryPage[Any]:
            return await repos.allocation.list_allocations_snapshot(limit=50, offset=0)

        allocations = await self._with_repositories(_query)
        return {
            "balance_usdc": decimal_text(account.balance_usdc),
            "allowance_usdc": decimal_text(account.allowance_usdc),
            "available_usdc": decimal_text(account.balance_usdc),
            "position_count": len(account.positions),
            "open_order_count": len(account.open_orders),
            "fill_count": len(account.fills),
            "pause_count": len(account.paused_markets),
            "last_reconcile_at": jsonable(account.last_reconcile_at),
            "user_ws_connected": account.user_ws_connected,
            "allow_new_entries": account.allow_new_entries,
            "markets_tracked": len(registry.markets),
            "recent_allocations": [
                self._serializer().allocation(allocation) for allocation in allocations.items
            ],
        }

    def workers_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
            return {
                "phase": payload.get("phase", "starting"),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "status_reason": payload.get("status_reason"),
                "queue_depths": payload.get("queue_depths"),
                "scheduler": payload.get("scheduler"),
                "workers": list(payload.get("worker_health", ())),
            }

        runtime_status = self._runtime_status_snapshot()
        return {
            "phase": runtime_status["phase"],
            "automatic_trading_enabled": bool(runtime_status.get("automatic_trading_enabled")),
            "status_reason": None,
            "queue_depths": runtime_status.get("queue_depth"),
            "scheduler": None,
            "workers": [],
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
            return {
                "phase": payload.get("phase", "starting"),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "status_reason": payload.get("status_reason"),
                "queue_depths": payload.get("queue_depths"),
                "metrics": payload.get("metrics"),
            }

        metrics = getattr(self.runtime, "metrics", None)
        metrics_payload = None
        if metrics is not None and hasattr(metrics, "snapshot"):
            snapshot = metrics.snapshot()
            metrics_payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
        runtime_status = self._runtime_status_snapshot()
        return {
            "phase": runtime_status["phase"],
            "automatic_trading_enabled": bool(runtime_status.get("automatic_trading_enabled")),
            "status_reason": None,
            "queue_depths": runtime_status.get("queue_depth"),
            "metrics": metrics_payload,
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
        condition_id_filter = normalize_condition_ids(condition_ids)
        result = await reconcile_worker.reconcile_once(
            trace_id=trace_id,
            condition_ids=condition_id_filter or None,
        )
        return self._serializer().reconcile_result(result)

    async def replace_order(
        self,
        *,
        order_id: str,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        new_price: Decimal,
        size_shares: Decimal | None = None,
        operator: str = "manual",
        reason: str = "admin_replace_order",
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._order_controller().replace_order(
            order_id=order_id,
            market_slug=market_slug,
            condition_id=condition_id,
            token_id=token_id,
            new_price=new_price,
            size_shares=size_shares,
            operator=operator,
            reason=reason,
            trace_id=trace_id,
        )

    def _runtime_status_snapshot(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else jsonable(snapshot)
            readiness = payload.get("readiness") or {}
            user_ws = payload.get("user_ws") or {}
            account = payload.get("account") or {}
            return {
                "phase": payload.get("phase", "starting"),
                "ready_to_trade": bool(readiness.get("ready")),
                "automatic_trading_enabled": bool(payload.get("automatic_trading_enabled")),
                "user_ws_connected": bool(user_ws.get("connected", account.get("user_ws_connected", False))),
                "allow_new_entries": bool(account.get("allow_new_entries", False)),
                "last_reconcile_at": readiness.get("last_reconcile_at") or account.get("last_reconcile_at"),
                "portfolio_budget_usdc": decimal_text(getattr(self._settings(), "portfolio_budget_usdc", None)),
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
        elif not account.user_ws_connected or not account.allow_new_entries:
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
            "ready_to_trade": ready_to_trade and account.user_ws_connected and account.allow_new_entries,
            "user_ws_connected": account.user_ws_connected,
            "allow_new_entries": account.allow_new_entries,
            "last_reconcile_at": jsonable(account.last_reconcile_at),
            "portfolio_budget_usdc": decimal_text(getattr(self._settings(), "portfolio_budget_usdc", None)),
            "queue_depth": jsonable(event_bus) if event_bus is not None else None,
            "persistence": jsonable(persistence) if persistence is not None else None,
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
        has_config_blockers = bool(blocking_issues)
        runtime_blocking_reason_list = tuple(str(reason) for reason in runtime_snapshot.get("blocking_reasons", ()))
        runtime_blocking_reasons = set(runtime_blocking_reason_list)
        seen_issue_keys = {
            (str(issue.get("field", "")), str(issue.get("code", "")))
            for issue in blocking_issues
            if isinstance(issue, Mapping)
        }

        def append_issue(field: str, code: str, message: str) -> None:
            issue_key = (field, code)
            if issue_key in seen_issue_keys:
                return
            seen_issue_keys.add(issue_key)
            blocking_issues.append(
                {
                    "field": field,
                    "code": code,
                    "message": message,
                }
            )

        # 首页阻塞栏只展示用户可以直接处理的根因。
        # Supervisor 的 blocking_reasons 保留在 runtime 快照里供排障，不再原样外泄到列表。
        for reason in runtime_blocking_reason_list:
            issue = self._runtime_blocking_issue_from_reason(reason, has_config_blockers=has_config_blockers)
            if issue is None:
                continue
            append_issue(str(issue["field"]), str(issue["code"]), str(issue["message"]))

        user_ws_connected = bool(runtime_snapshot.get("user_ws_connected"))
        last_reconcile_at = runtime_snapshot.get("last_reconcile_at")
        allow_new_entries = bool(runtime_snapshot.get("allow_new_entries"))
        has_runtime_client_blocker = {
            "trading_client_not_ready",
            "trading_client_unavailable",
        }.intersection(runtime_blocking_reasons)
        expose_runtime_account_blockers = not has_config_blockers and not has_runtime_client_blocker
        if expose_runtime_account_blockers and not user_ws_connected:
            append_issue(
                "user_ws_connected",
                "ws_disconnected",
                "用户行情连接未连接，暂停自动下单",
            )
        if expose_runtime_account_blockers and last_reconcile_at is None:
            append_issue(
                "last_reconcile_at",
                "reconcile_pending",
                "首次 reconcile 未完成，禁止自动下单",
            )
        if expose_runtime_account_blockers and not allow_new_entries and user_ws_connected and last_reconcile_at is not None:
            append_issue(
                "allow_new_entries",
                "buy_gate_closed",
                "自动买入闸门关闭",
            )
        return blocking_issues

    def _runtime_blocking_issue_from_reason(
        self,
        reason: str,
        *,
        has_config_blockers: bool,
    ) -> dict[str, str] | None:
        if reason in {
            "config_not_ready",
            "user_ws_not_connected",
            "reconcile_not_fresh",
        }:
            return None
        if reason.startswith("phase="):
            return None
        if reason == "db_not_ready" or reason == "database_unavailable":
            return {
                "field": "database",
                "code": "database_unavailable",
                "message": "数据库连接未就绪，暂停自动下单",
            }
        if reason == "market_ws_not_connected":
            return {
                "field": "market_ws_connected",
                "code": "ws_disconnected",
                "message": "市场行情连接未连接，暂停自动下单",
            }
        if reason == "outbox_backlog_high":
            return {
                "field": "outbox_depth",
                "code": "backlog_high",
                "message": "外发队列积压过高，暂停自动下单",
            }
        if reason == "trading_client_not_ready":
            if has_config_blockers:
                return None
            return {
                "field": "trading_client",
                "code": "client_not_ready",
                "message": "交易客户端未就绪，暂停自动下单",
            }
        if reason == "trading_client_unavailable":
            if has_config_blockers:
                return None
            return {
                "field": "trading_client",
                "code": "client_unavailable",
                "message": "交易客户端不可用，暂停自动下单",
            }
        if reason.startswith("startup_reconcile_failed:"):
            detail = reason.split(":", 1)[1].strip()
            message = "启动对账失败，暂停自动下单"
            if detail:
                message = f"{message}：{detail}"
            return {
                "field": "startup_reconcile",
                "code": "startup_reconcile_failed",
                "message": message,
            }
        return None

    def _readiness_summary(self) -> dict[str, Any]:
        supervisor = getattr(self.runtime, "supervisor", None)
        if supervisor is not None and hasattr(supervisor, "snapshot"):
            snapshot = supervisor.snapshot()
            readiness = snapshot.readiness
            if readiness is not None:
                return readiness.as_dict() if hasattr(readiness, "as_dict") else jsonable(readiness)
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
        return jsonable(settings)

    def _identity_snapshot(self) -> dict[str, Any]:
        settings = self._settings()
        wallet_address = None
        for component_name in ("clob_client", "data_client"):
            component = getattr(self.runtime, component_name, None)
            if component is None:
                continue
            candidate = getattr(component, "default_wallet_address", None)
            if callable(candidate):
                candidate = candidate()
            if candidate:
                wallet_address = str(candidate)
                break
        return {
            "wallet_address": wallet_address,
            "funder_address": (
                getattr(settings, "polymarket_funder_address", None) if settings is not None else None
            ),
            "signature_type": (
                getattr(settings, "polymarket_signature_type", None) if settings is not None else None
            ),
        }

    def _serializer(self) -> AdminSerializer:
        return AdminSerializer(
            account_snapshot_provider=self._account_snapshot,
            registry_snapshot_provider=self._registry_snapshot,
            market_ws_snapshot=self._market_ws_snapshot,
        )

    def _order_controller(self) -> AdminOrderController:
        return AdminOrderController(
            runtime=self.runtime,
            serializer=self._serializer(),
            account_snapshot=self._account_snapshot,
            resolve_market=self._resolve_market,
            trading_service=self._trading_service,
            find_open_order=self._find_open_order,
        )

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

    def _market_discovery_snapshot(self) -> dict[str, Any]:
        state = getattr(self.runtime, "market_discovery_scan", None)
        if state is None:
            return {
                "round_id": 0,
                "cursor_active": False,
                "round_started_at": None,
                "last_round_completed_at": None,
                "pages_scanned_in_round": 0,
                "markets_seen_in_round": 0,
                "last_completed_round_pages": 0,
                "last_completed_round_markets": 0,
                "last_page_size": 0,
                "last_tick_started_at": None,
                "last_tick_completed_at": None,
                "last_tick_requests": 0,
                "last_tick_markets": 0,
                "last_error": None,
                "consecutive_failures": 0,
            }
        return {
            "round_id": int(getattr(state, "round_id", 0)),
            "cursor_active": getattr(state, "after_cursor", None) is not None,
            "round_started_at": jsonable(getattr(state, "round_started_at", None)),
            "last_round_completed_at": jsonable(getattr(state, "last_round_completed_at", None)),
            "pages_scanned_in_round": int(getattr(state, "pages_scanned_in_round", 0)),
            "markets_seen_in_round": int(getattr(state, "markets_seen_in_round", 0)),
            "last_completed_round_pages": int(getattr(state, "last_completed_round_pages", 0)),
            "last_completed_round_markets": int(getattr(state, "last_completed_round_markets", 0)),
            "last_page_size": int(getattr(state, "last_page_size", 0)),
            "last_tick_started_at": jsonable(getattr(state, "last_tick_started_at", None)),
            "last_tick_completed_at": jsonable(getattr(state, "last_tick_completed_at", None)),
            "last_tick_requests": int(getattr(state, "last_tick_requests", 0)),
            "last_tick_markets": int(getattr(state, "last_tick_markets", 0)),
            "last_error": getattr(state, "last_error", None),
            "consecutive_failures": int(getattr(state, "consecutive_failures", 0)),
        }

    def _has_db_session_factory(self) -> bool:
        return getattr(self.runtime, "db_session_factory", None) is not None

    def _market_ws_snapshot(self, token_id: str) -> OrderbookSnapshot | None:
        worker = getattr(self.runtime, "market_ws_worker", None)
        if worker is None:
            return None
        snapshot = getattr(worker, "snapshot", None)
        if not callable(snapshot):
            return None
        return snapshot(token_id)

    def _settings(self) -> Any | None:
        return getattr(self.runtime, "settings", None)

    def _clob_client(self) -> Any:
        clob_client = getattr(self.runtime, "clob_client", None)
        if clob_client is None:
            raise RuntimeError("clob_client unavailable")
        return clob_client

    def _trading_service(self) -> TradingService:
        trading_service = getattr(self.runtime, "trading_service", None)
        if trading_service is None:
            raise RuntimeError("trading_service unavailable")
        return trading_service

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
                market = registry.get_by_token_id(token_id)
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
                outbox=OutboxEventRepository(session),
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

    def _find_open_order(
        self,
        snapshot: AccountSnapshot,
        *,
        order_id: str,
        market_slug: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
    ) -> Order | None:
        matches = [
            order
            for order in snapshot.open_orders
            if order.open
            and order_id in {normalize_order_id(order), order.order_id, order.idempotency_key}
            and (market_slug is None or order.market_slug == market_slug)
            and (condition_id is None or order.condition_id == condition_id)
            and (token_id is None or order.token_id == token_id)
        ]
        if len(matches) != 1:
            return None
        return matches[0]

@dataclass(frozen=True, slots=True)
class _RepositoryGroup:
    audit: AuditEventRepository
    market: MarketRepository
    order: OrderRepository
    fill: FillRepository
    position: PositionRepository
    allocation: AllocationRepository
    outbox: OutboxEventRepository
