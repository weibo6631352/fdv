from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Protocol, cast

from polymarket_trader.domain.events import Fill
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import OrderRecord
from polymarket_trader.domain.orderbook import OrderbookSnapshot
from polymarket_trader.domain.position import Position
from polymarket_trader.runtime.account_state import AccountStateStore
from polymarket_trader.runtime.registry import MarketRegistry, MarketRegistrySnapshot
from polymarket_trader.workers.market_ws_worker import MarketWsWorker

RegistrySnapshotProvider = Callable[[], MarketRegistrySnapshot]


class MarketAuthorityClient(Protocol):
    async def list_markets(
        self,
        *,
        active: bool | None = True,
        closed: bool | None = False,
        tag: str | None = None,
        slug: str | None = None,
        limit: int = 100,
        offset: int = 0,
        timeout_s: float | None = None,
    ) -> tuple[Any, ...]: ...


class OrderAuthorityClient(Protocol):
    @property
    def has_auth_client(self) -> bool: ...

    async def get_orderbook(
        self,
        token_id: str,
        *,
        market_slug: str | None = None,
        condition_id: str | None = None,
    ) -> Any: ...

    async def get_fee_rate(self, token_id: str) -> int | None: ...

    async def list_open_orders(self) -> tuple[Any, ...]: ...

    async def list_fills(self) -> tuple[Any, ...]: ...

    async def get_balance_allowance(self) -> Any: ...


class DataAuthorityClient(Protocol):
    @property
    def has_auth_client(self) -> bool: ...

    async def list_positions(self) -> tuple[Any, ...]: ...


class GammaMarketCandidate(Protocol):
    condition_id: str
    market_slug: str
    clob_enabled: bool | None
    outcomes: tuple[Any, ...]

    def to_market(self) -> Market: ...


class TradingAuthorityClient(Protocol):
    pass


@dataclass(frozen=True, slots=True)
class AuthoritativeMarketRefresh:
    requested_market: Market
    refreshed_market: Market | None
    orderbook_snapshots: tuple[OrderbookSnapshot, ...] = ()
    fee_rate_refreshed: bool = False
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoritativeRefreshSummary:
    trace_id: str
    market_count: int
    refreshed_markets: int
    refreshed_orderbooks: int
    refreshed_fee_rates: int
    refreshed_positions: int
    refreshed_open_orders: int
    refreshed_fills: int
    refreshed_balance: bool
    refreshed_allowance: bool
    user_refresh_enabled: bool
    failures: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "market_count": self.market_count,
            "refreshed_markets": self.refreshed_markets,
            "refreshed_orderbooks": self.refreshed_orderbooks,
            "refreshed_fee_rates": self.refreshed_fee_rates,
            "refreshed_positions": self.refreshed_positions,
            "refreshed_open_orders": self.refreshed_open_orders,
            "refreshed_fills": self.refreshed_fills,
            "refreshed_balance": self.refreshed_balance,
            "refreshed_allowance": self.refreshed_allowance,
            "user_refresh_enabled": self.user_refresh_enabled,
            "failures": list(self.failures),
        }


class ReconcileAuthorityRefresher:
    def __init__(
        self,
        *,
        registry_snapshot_provider: RegistrySnapshotProvider | None = None,
        account_state_store: AccountStateStore | None = None,
        registry: MarketRegistry | None = None,
        market_ws_worker: MarketWsWorker | None = None,
        gamma_client: MarketAuthorityClient | None = None,
        clob_client: OrderAuthorityClient | None = None,
        data_client: DataAuthorityClient | None = None,
        trading_client: TradingAuthorityClient | None = None,
    ) -> None:
        self._registry_snapshot_provider = registry_snapshot_provider
        self._account_state_store = account_state_store
        self._registry = registry
        self._market_ws_worker = market_ws_worker
        self._gamma_client = gamma_client
        self._clob_client = clob_client
        self._data_client = data_client
        self._trading_client = trading_client

    async def refresh(
        self,
        *,
        trace_id: str,
        condition_ids: tuple[str, ...] | None = None,
    ) -> AuthoritativeRefreshSummary:
        markets = self._target_markets(condition_ids=condition_ids)
        if not markets:
            return AuthoritativeRefreshSummary(
                trace_id=trace_id,
                market_count=0,
                refreshed_markets=0,
                refreshed_orderbooks=0,
                refreshed_fee_rates=0,
                refreshed_positions=0,
                refreshed_open_orders=0,
                refreshed_fills=0,
                refreshed_balance=False,
                refreshed_allowance=False,
                user_refresh_enabled=self._trading_client is not None,
            )

        market_refreshes = await asyncio.gather(
            *(self._refresh_market_authority(market) for market in markets),
            return_exceptions=True,
        )
        refresh_failures: list[str] = []
        refreshed_markets = 0
        refreshed_orderbooks = 0
        refreshed_fee_rates = 0

        for item in market_refreshes:
            if isinstance(item, BaseException):
                refresh_failures.append(str(item))
                continue
            if item.refreshed_market is not None:
                refreshed_markets += 1
                self._apply_refreshed_market(item.refreshed_market)
            if item.orderbook_snapshots:
                refreshed_orderbooks += len(item.orderbook_snapshots)
                await self._apply_refreshed_orderbooks(
                    item.refreshed_market or item.requested_market,
                    item.orderbook_snapshots,
                )
            if item.fee_rate_refreshed:
                refreshed_fee_rates += 1
            refresh_failures.extend(item.failures)

        account_summary = await self.refresh_account(trace_id=trace_id, markets=markets)
        refresh_failures.extend(account_summary.failures)

        return AuthoritativeRefreshSummary(
            trace_id=trace_id,
            market_count=len(markets),
            refreshed_markets=refreshed_markets,
            refreshed_orderbooks=refreshed_orderbooks,
            refreshed_fee_rates=refreshed_fee_rates,
            refreshed_positions=account_summary.refreshed_positions,
            refreshed_open_orders=account_summary.refreshed_open_orders,
            refreshed_fills=account_summary.refreshed_fills,
            refreshed_balance=account_summary.refreshed_balance,
            refreshed_allowance=account_summary.refreshed_allowance,
            user_refresh_enabled=account_summary.user_refresh_enabled,
            failures=tuple(refresh_failures),
        )

    async def refresh_account(
        self,
        *,
        trace_id: str,
        markets: tuple[Market, ...],
    ) -> AuthoritativeRefreshSummary:
        failures: list[str] = []
        user_refresh_enabled = bool(
            self._trading_client is not None
            or (
                self._data_client is not None
                and self._clob_client is not None
                and self._data_client.has_auth_client
                and self._clob_client.has_auth_client
            )
        )
        if not user_refresh_enabled:
            return AuthoritativeRefreshSummary(
                trace_id=trace_id,
                market_count=len(markets),
                refreshed_markets=0,
                refreshed_orderbooks=0,
                refreshed_fee_rates=0,
                refreshed_positions=0,
                refreshed_open_orders=0,
                refreshed_fills=0,
                refreshed_balance=False,
                refreshed_allowance=False,
                user_refresh_enabled=False,
                failures=(),
            )

        positions_task = asyncio.create_task(self._fetch_positions(failures))
        open_orders_task = asyncio.create_task(self._fetch_open_orders(failures))
        fills_task = asyncio.create_task(self._fetch_fills(failures))
        balance_task = asyncio.create_task(self._fetch_balance(failures))
        positions, open_orders, fills, balance_result = await asyncio.gather(
            positions_task,
            open_orders_task,
            fills_task,
            balance_task,
        )
        balance, allowance, balance_refreshed, allowance_refreshed = balance_result

        if self._account_state_store is not None:
            if positions is not None:
                self._account_state_store.replace_positions(positions)
            if open_orders is not None:
                self._account_state_store.replace_open_orders(open_orders)
            if fills is not None:
                self._account_state_store.replace_fills(fills)
            if balance_refreshed or allowance_refreshed:
                self._account_state_store.update_balances(
                    balance_usdc=balance,
                    allowance_usdc=allowance,
                )

        return AuthoritativeRefreshSummary(
            trace_id=trace_id,
            market_count=len(markets),
            refreshed_markets=0,
            refreshed_orderbooks=0,
            refreshed_fee_rates=0,
            refreshed_positions=0 if positions is None else len(positions),
            refreshed_open_orders=0 if open_orders is None else len(open_orders),
            refreshed_fills=0 if fills is None else len(fills),
            refreshed_balance=balance_refreshed,
            refreshed_allowance=allowance_refreshed,
            user_refresh_enabled=True,
            failures=tuple(failures),
        )

    def _target_markets(self, *, condition_ids: tuple[str, ...] | None = None) -> tuple[Market, ...]:
        condition_id_filter = set(condition_ids or ())
        if self._registry_snapshot_provider is not None:
            markets = self._registry_snapshot_provider().markets
        elif self._registry is not None:
            markets = self._registry.snapshot().markets
        else:
            markets = tuple()
        if not condition_id_filter:
            return markets
        return tuple(market for market in markets if market.condition_id in condition_id_filter)

    async def _refresh_market_authority(self, market: Market) -> AuthoritativeMarketRefresh:
        failures: list[str] = []
        refreshed_market = await self._fetch_gamma_market(market, failures)
        market_for_orderbook = refreshed_market or market
        fee_rate_bps = None
        if (
            market_for_orderbook.fee_rate_bps is None
            and market_for_orderbook.taker_base_fee_bps is None
        ):
            fee_rate_bps = await self._fetch_fee_rate(market_for_orderbook, failures)
        fee_rate_refreshed = fee_rate_bps is not None
        if fee_rate_bps is not None:
            market_for_orderbook = market_for_orderbook.with_fee_rate(
                fee_rate_bps,
                fee_rate_updated_at=_utc_now(),
            )
            refreshed_market = market_for_orderbook
        orderbook_snapshots = await self._fetch_orderbook_snapshots(
            market_for_orderbook,
            failures,
        )
        return AuthoritativeMarketRefresh(
            requested_market=market,
            refreshed_market=refreshed_market,
            orderbook_snapshots=orderbook_snapshots,
            fee_rate_refreshed=fee_rate_refreshed,
            failures=tuple(failures),
        )

    async def _fetch_gamma_market(
        self,
        market: Market,
        failures: list[str],
    ) -> Market | None:
        if self._gamma_client is None:
            return None
        for slug in (market.market_slug, market.event_slug):
            if not slug:
                continue
            try:
                candidates = await self._gamma_client.list_markets(
                    slug=str(slug),
                    active=None,
                    closed=None,
                    limit=25,
                )
                gamma_market = _pick_gamma_market(candidates, market)
                if gamma_market is None:
                    failures.append(f"gamma:{market.condition_id}:{slug}:not_found")
                    continue
                refreshed_market = self._merge_gamma_market(
                    market,
                    gamma_market.to_market(),
                    gamma_market.clob_enabled,
                )
                return refreshed_market
            except Exception as exc:  # pragma: no cover - external SDK failure path
                failures.append(f"gamma:{market.condition_id}:{slug}:{exc}")
        return None

    async def _fetch_orderbook_snapshots(
        self,
        market: Market,
        failures: list[str],
    ) -> tuple[OrderbookSnapshot, ...]:
        if self._clob_client is None:
            return ()
        snapshots: list[OrderbookSnapshot] = []
        for token_id in market.token_ids:
            try:
                orderbook = await self._clob_client.get_orderbook(
                    token_id,
                    market_slug=market.market_slug,
                    condition_id=market.condition_id,
                )
            except Exception as exc:  # pragma: no cover - external SDK failure path
                failures.append(f"clob:{market.condition_id}:{token_id}:{exc}")
                continue
            snapshots.append(orderbook.to_snapshot())
        return tuple(snapshots)

    async def _apply_refreshed_orderbooks(
        self,
        market: Market,
        snapshots: tuple[OrderbookSnapshot, ...],
    ) -> None:
        if self._market_ws_worker is None:
            return
        for snapshot in snapshots:
            await self._market_ws_worker.apply_rest_snapshot(
                snapshot.token_id,
                snapshot,
                source="reconcile_rest",
            )

    def _apply_refreshed_market(self, market: Market) -> None:
        if self._market_ws_worker is not None:
            self._market_ws_worker.track_market(market)
            return
        if self._registry is not None:
            self._registry.upsert(market)

    def _merge_gamma_market(
        self,
        current: Market,
        refreshed: Market,
        clob_enabled: bool | None,
    ) -> Market:
        merged = current.with_metadata(
            event_id=refreshed.event_id,
            event_title=refreshed.event_title,
            event_slug=refreshed.event_slug,
            icon_url=refreshed.icon_url,
            end_date=refreshed.end_date,
            category=refreshed.category,
            tags=refreshed.tags,
            matched_keywords=current.matched_keywords,
            outcomes=refreshed.outcomes,
            neg_risk=refreshed.neg_risk,
        )
        merged = merged.with_tick_size(refreshed.tick_size)
        merged = merged.with_min_order_size(refreshed.min_order_size)
        merged = merged.with_fee_schedule(
            fees_enabled=refreshed.fees_enabled,
            maker_base_fee_bps=refreshed.maker_base_fee_bps,
            taker_base_fee_bps=refreshed.taker_base_fee_bps,
        )

        desired_status = refreshed.trading_status
        reject_reason = refreshed.reject_reason
        if clob_enabled is False and desired_status == TradingStatus.ELIGIBLE:
            desired_status = TradingStatus.PAUSED
            reject_reason = reject_reason or "orderbook_disabled"

        if current.trading_status in {
            TradingStatus.RESOLVED,
            TradingStatus.REJECTED,
        }:
            desired_status = current.trading_status
            reject_reason = current.reject_reason
        elif (
            current.trading_status == TradingStatus.PAUSED
            and current.reject_reason == "manual_pause"
            and desired_status == TradingStatus.ELIGIBLE
        ):
            desired_status = TradingStatus.PAUSED
            reject_reason = current.reject_reason

        return merged.with_trading_status(desired_status, reject_reason=reject_reason)

    async def _fetch_fee_rate(
        self,
        market: Market,
        failures: list[str],
    ) -> int | None:
        if self._clob_client is None:
            return None
        token_id = next(iter(market.token_ids), None)
        if token_id is None:
            return None
        try:
            return await self._clob_client.get_fee_rate(token_id)
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:fee_rate:{market.condition_id}:{token_id}:{exc}")
            return None

    async def _fetch_positions(
        self,
        failures: list[str],
    ) -> tuple[Position, ...] | None:
        if self._data_client is None:
            return None
        try:
            positions = await self._data_client.list_positions()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"data:positions:{exc}")
            return None
        return tuple(position.to_position() for position in positions)

    async def _fetch_open_orders(
        self,
        failures: list[str],
    ) -> tuple[OrderRecord, ...] | None:
        if self._clob_client is None:
            return None
        try:
            orders = await self._clob_client.list_open_orders()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:open_orders:{exc}")
            return None
        return tuple(order.to_order_record() for order in orders)

    async def _fetch_fills(
        self,
        failures: list[str],
    ) -> tuple[Fill, ...] | None:
        if self._clob_client is None:
            return None
        try:
            fills = await self._clob_client.list_fills()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:fills:{exc}")
            return None
        return tuple(fill.to_fill() for fill in fills)

    async def _fetch_balance(
        self,
        failures: list[str],
    ) -> tuple[Decimal, Decimal, bool, bool]:
        if self._clob_client is None:
            return Decimal("0"), Decimal("0"), False, False
        try:
            balance = await self._clob_client.get_balance_allowance()
        except Exception as exc:  # pragma: no cover - external SDK failure path
            failures.append(f"clob:balance_allowance:{exc}")
            return Decimal("0"), Decimal("0"), False, False
        return balance.balance_usdc, balance.allowance_usdc, True, True


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _pick_gamma_market(
    candidates: tuple[object, ...],
    market: Market,
) -> GammaMarketCandidate | None:
    for candidate in candidates:
        if getattr(candidate, "condition_id", None) == market.condition_id:
            return cast(GammaMarketCandidate, candidate)
    for candidate in candidates:
        candidate_outcomes = getattr(candidate, "outcomes", ())
        candidate_token_ids = tuple(
            getattr(outcome, "token_id", None)
            for outcome in candidate_outcomes
            if getattr(outcome, "token_id", None)
        )
        if set(candidate_token_ids).intersection(market.token_ids):
            return cast(GammaMarketCandidate, candidate)
    for candidate in candidates:
        if getattr(candidate, "market_slug", None) == market.market_slug:
            return cast(GammaMarketCandidate, candidate)
    return None
