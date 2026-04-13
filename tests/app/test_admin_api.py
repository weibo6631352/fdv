from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

from polymarket_trader.api.app import create_app
from polymarket_trader.app.admin_service import AdminService
from polymarket_trader.domain.allocation import Allocation
from polymarket_trader.app.reconcile_service import (
    ReconcileAction,
    ReconcileActionType,
    ReconcileMarketPlan,
    ReconcilePlan,
)
from polymarket_trader.config import Settings
from polymarket_trader.domain.events import AuditEvent, Fill, OutboxEvent
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import (
    CancelOrderIntent,
    ExecutionTimestamps,
    Order,
    OrderRecord,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    SellOrderIntent,
)
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.domain.position import Position
from polymarket_trader.infra.db import RepositoryPage
from polymarket_trader.infra.polymarket import PolymarketResponseError
from polymarket_trader.infra.polymarket.schemas import (
    normalize_activity_payload,
    normalize_closed_position_payload,
    normalize_gamma_profile,
    normalize_gamma_profile_search,
    normalize_market_holders_payload,
    normalize_market_positions_payload,
    normalize_orderbook_payload,
    normalize_position_payload,
    normalize_price_history_payload,
    normalize_trade_payload,
    normalize_user_value_payload,
)
from polymarket_trader.runtime.account_state import AccountStateStore
from polymarket_trader.runtime.event_bus import EventBus
from polymarket_trader.runtime.registry import MarketRegistry
from polymarket_trader.runtime.status import ReadinessSnapshot, RuntimePhase, RuntimeSnapshot


@dataclass(frozen=True, slots=True)
class FakeConfigReadiness:
    ready_to_trade: bool
    warnings: tuple[str, ...] = ()
    blocking_issues: tuple[dict[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "ready_to_trade": self.ready_to_trade,
            "warnings": list(self.warnings),
            "blocking_issues": list(self.blocking_issues),
        }


@dataclass(frozen=True, slots=True)
class FakePersistenceSnapshot:
    outbox_depth: int
    last_error: str | None = None
    last_persisted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FakeTradeReview:
    operation: str
    submitted: bool
    risk_decision: object | None
    order_result: OrderResult | None
    submission_error: str | None = None


@dataclass(frozen=True, slots=True)
class FakeRiskDecision:
    passed: bool
    reason: str = "passed"
    retryable: bool = False


class FakeMarketWsWorker:
    def __init__(self, snapshots: dict[str, OrderbookSnapshot]) -> None:
        self._snapshots = snapshots

    def snapshot(self, token_id: str) -> OrderbookSnapshot | None:
        return self._snapshots.get(token_id)


class FakeSupervisor:
    def __init__(self, snapshot: RuntimeSnapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot


class FakeGammaClient:
    def __init__(self, *, profile: object | None = None, error: Exception | None = None) -> None:
        self._profile = profile or normalize_gamma_profile(
            {
                "createdAt": "2026-01-01T12:00:00Z",
                "proxyWallet": "0x1111111111111111111111111111111111111111",
                "profileImage": "https://example.com/profile.png",
                "displayUsernamePublic": True,
                "bio": "market watcher",
                "pseudonym": "market-watch-001",
                "name": "Market Watcher",
                "users": [
                    {
                        "id": "user-1",
                        "creator": True,
                        "mod": False,
                    }
                ],
                "xUsername": "marketwatcher",
                "verifiedBadge": True,
            }
        )
        self._search_result = normalize_gamma_profile_search(
            {
                "profiles": [
                    {
                        "id": "profile-1",
                        "name": "Market Watcher",
                        "pseudonym": "market-watch-001",
                        "displayUsernamePublic": True,
                        "profileImage": "https://example.com/profile.png",
                        "profileImageOptimized": {
                            "imageUrlOptimized": "https://example.com/profile-optimized.png",
                        },
                        "bio": "market watcher",
                        "proxyWallet": "0x1111111111111111111111111111111111111111",
                        "createdAt": "2026-01-01T12:00:00Z",
                        "updatedAt": "2026-01-02T12:00:00Z",
                        "walletActivated": True,
                        "isCloseOnly": False,
                        "isCertReq": False,
                    }
                ],
                "pagination": {
                    "hasMore": False,
                    "totalResults": 1,
                },
            }
        )
        self._error = error
        self.calls: list[str] = []
        self.search_calls: list[dict[str, object]] = []

    async def get_public_profile(self, address: str) -> object:
        self.calls.append(address)
        if self._error is not None:
            raise self._error
        return self._profile

    async def search_public_profiles(self, query: str, **kwargs: object) -> object:
        self.search_calls.append({"query": query, **kwargs})
        if self._error is not None:
            raise self._error
        return self._search_result


class FakeDataClient:
    def __init__(
        self,
        *,
        activities: tuple[object, ...] | None = None,
        holders: tuple[object, ...] | None = None,
        market_positions: tuple[object, ...] | None = None,
        trades: tuple[object, ...] | None = None,
        user_value: object | None = None,
        positions: tuple[object, ...] | None = None,
        closed_positions: tuple[object, ...] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._activities = activities or (
            normalize_activity_payload(
                {
                    "proxyWallet": "0x1111111111111111111111111111111111111111",
                    "timestamp": 1704100800,
                    "conditionId": "0x" + "1" * 64,
                    "type": "TRADE",
                    "size": 5,
                    "usdcSize": 3.5,
                    "transactionHash": "0xtrade1",
                    "price": 0.7,
                    "asset": "no-token-500m",
                    "side": "SELL",
                    "outcomeIndex": 1,
                    "title": "Sample Market A",
                    "slug": "sample-market-a",
                    "icon": "https://example.com/icon.png",
                    "eventSlug": "sample-event-a",
                    "outcome": "No",
                    "name": "Market Watcher",
                    "pseudonym": "market-watch-001",
                    "bio": "market watcher",
                    "profileImage": "https://example.com/profile.png",
                    "profileImageOptimized": "https://example.com/profile-optimized.png",
                }
            ),
        )
        self._holders = holders or (
            normalize_market_holders_payload(
                {
                    "token": "no-token-500m",
                    "holders": [
                        {
                            "proxyWallet": "0x1111111111111111111111111111111111111111",
                            "bio": "market watcher",
                            "asset": "no-token-500m",
                            "pseudonym": "market-watch-001",
                            "amount": 25,
                            "displayUsernamePublic": True,
                            "outcomeIndex": 1,
                            "name": "Market Watcher",
                            "profileImage": "https://example.com/profile.png",
                            "profileImageOptimized": "https://example.com/profile-optimized.png",
                        }
                    ],
                }
            ),
        )
        self._market_positions = market_positions or (
            normalize_market_positions_payload(
                {
                    "token": "no-token-500m",
                    "positions": [
                        {
                            "proxyWallet": "0x1111111111111111111111111111111111111111",
                            "name": "Market Watcher",
                            "profileImage": "https://example.com/profile.png",
                            "verified": True,
                            "asset": "no-token-500m",
                            "conditionId": "0x" + "1" * 64,
                            "avgPrice": 0.5,
                            "size": 5,
                            "currPrice": 0.6,
                            "currentValue": 3,
                            "cashPnl": 0.5,
                            "totalBought": 2.5,
                            "realizedPnl": 0.1,
                            "totalPnl": 0.6,
                            "outcome": "No",
                            "outcomeIndex": 1,
                        }
                    ],
                }
            ),
        )
        self._trades = trades or (
            normalize_trade_payload(
                {
                    "proxyWallet": "0x1111111111111111111111111111111111111111",
                    "asset": "no-token-500m",
                    "conditionId": "0x" + "1" * 64,
                    "side": "SELL",
                    "size": 5,
                    "price": 0.7,
                    "timestamp": 1704100800,
                    "title": "Sample Market A",
                    "slug": "sample-market-a",
                    "icon": "https://example.com/icon.png",
                    "eventSlug": "sample-event-a",
                    "outcome": "No",
                    "outcomeIndex": 1,
                    "name": "Market Watcher",
                    "pseudonym": "market-watch-001",
                    "bio": "market watcher",
                    "profileImage": "https://example.com/profile.png",
                    "profileImageOptimized": "https://example.com/profile-optimized.png",
                    "transactionHash": "0xtrade2",
                }
            ),
        )
        self._user_value = user_value or normalize_user_value_payload(
            {
                "user": "0x1111111111111111111111111111111111111111",
                "value": 123.45,
            }
        )
        self._positions = positions or (
            normalize_position_payload(
                {
                    "proxyWallet": "0x1111111111111111111111111111111111111111",
                    "asset": "no-token-500m",
                    "conditionId": "0x" + "1" * 64,
                    "size": 5,
                    "avgPrice": 0.5,
                    "initialValue": 2.5,
                    "currentValue": 3,
                    "cashPnl": 0.5,
                    "percentPnl": 20,
                    "totalBought": 5,
                    "realizedPnl": 0.1,
                    "percentRealizedPnl": 2,
                    "curPrice": 0.6,
                    "redeemable": False,
                    "mergeable": False,
                    "title": "Sample Market A",
                    "slug": "sample-market-a",
                    "icon": "https://example.com/icon.png",
                    "eventSlug": "sample-event-a",
                    "outcome": "No",
                    "outcomeIndex": 1,
                    "oppositeOutcome": "Yes",
                    "oppositeAsset": "yes-token-500m",
                    "endDate": "2026-02-01T00:00:00Z",
                    "negativeRisk": False,
                }
            ),
        )
        self._closed_positions = closed_positions or (
            normalize_closed_position_payload(
                {
                    "proxyWallet": "0x1111111111111111111111111111111111111111",
                    "asset": "yes-token-1b",
                    "conditionId": "0x" + "2" * 64,
                    "avgPrice": 0.42,
                    "totalBought": 10,
                    "realizedPnl": 2.5,
                    "curPrice": 1,
                    "timestamp": 1704100800,
                    "title": "Sample Market B",
                    "slug": "sample-market-b",
                    "icon": "https://example.com/icon-1b.png",
                    "eventSlug": "sample-event-b",
                    "outcome": "Yes",
                    "outcomeIndex": 0,
                    "oppositeOutcome": "No",
                    "oppositeAsset": "no-token-1b",
                    "endDate": "2026-03-01T00:00:00Z",
                }
            ),
        )
        self._error = error
        self.calls: list[dict[str, object]] = []
        self.holder_calls: list[dict[str, object]] = []
        self.market_position_calls: list[dict[str, object]] = []
        self.trade_calls: list[dict[str, object]] = []
        self.value_calls: list[dict[str, object]] = []
        self.position_calls: list[dict[str, object]] = []
        self.closed_position_calls: list[dict[str, object]] = []

    async def list_activity(self, **kwargs: object) -> tuple[object, ...]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._activities

    async def list_holders(self, **kwargs: object) -> tuple[object, ...]:
        self.holder_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._holders

    async def list_market_positions(self, **kwargs: object) -> tuple[object, ...]:
        self.market_position_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._market_positions

    async def list_trades(self, **kwargs: object) -> tuple[object, ...]:
        self.trade_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._trades

    async def get_user_value(self, **kwargs: object) -> object:
        self.value_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._user_value

    async def list_positions(self, **kwargs: object) -> tuple[object, ...]:
        self.position_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._positions

    async def list_closed_positions(self, **kwargs: object) -> tuple[object, ...]:
        self.closed_position_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._closed_positions


class FakeClobClient:
    def __init__(
        self,
        *,
        history: object | None = None,
        orderbook: object | None = None,
        midpoint: Decimal | None = None,
        error: Exception | None = None,
    ) -> None:
        self._history = history or normalize_price_history_payload(
            {
                "history": [
                    {"t": 1704100800, "p": 0.52},
                    {"t": 1704104400, "p": 0.54},
                ]
            }
        )
        self._orderbook = orderbook or normalize_orderbook_payload(
            {
                "market": "condition-500m",
                "asset_id": "no-token-500m",
                "timestamp": 1704100800,
                "bids": [{"price": "0.55", "size": "100"}],
                "asks": [{"price": "0.59", "size": "200"}],
                "min_order_size": "1",
                "tick_size": "0.01",
                "last_trade_price": "0.54",
            },
            token_id="no-token-500m",
            market_slug="sample-market-a",
            condition_id="condition-500m",
        )
        self._midpoint = midpoint or Decimal("0.57")
        self._error = error
        self.history_calls: list[dict[str, object]] = []
        self.orderbook_calls: list[dict[str, object]] = []
        self.midpoint_calls: list[dict[str, object]] = []

    async def get_orderbook(self, token_id: str, **kwargs: object) -> object:
        self.orderbook_calls.append({"token_id": token_id, **kwargs})
        if self._error is not None:
            raise self._error
        return self._orderbook

    async def get_midpoint(self, token_id: str, **kwargs: object) -> Decimal:
        self.midpoint_calls.append({"token_id": token_id, **kwargs})
        if self._error is not None:
            raise self._error
        return self._midpoint

    async def get_prices_history(self, token_id: str, **kwargs: object) -> object:
        self.history_calls.append({"token_id": token_id, **kwargs})
        if self._error is not None:
            raise self._error
        return self._history


class FakeReconcileWorker:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str | None, tuple[str, ...] | None]] = []

    async def reconcile_once(
        self,
        *,
        trace_id: str | None = None,
        condition_ids: tuple[str, ...] | None = None,
    ) -> object:
        self.calls.append((trace_id, condition_ids))
        return self.result


class FakeStrategyService:
    def build_cancel_intent(
        self,
        *,
        trace_id: str,
        condition_id: str,
        no_token_id: str,
        order_id: str,
        market_slug: str | None = None,
        reason: str = "",
    ) -> CancelOrderIntent:
        return CancelOrderIntent(
            trace_id=trace_id,
            condition_id=condition_id,
            token_id=no_token_id,
            order_id=order_id,
            market_slug=market_slug,
            reason=reason,
        )


class FakeTradingService:
    def __init__(self) -> None:
        self.cancel_calls: list[CancelOrderIntent] = []
        self.sell_calls: list[SellOrderIntent] = []

    async def cancel(self, intent: CancelOrderIntent, *, operation: str = "cancel") -> FakeTradeReview:
        self.cancel_calls.append(intent)
        result = OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.CANCELLED,
            intent=intent,
            order_id=intent.order_id,
            reason=intent.reason or operation,
        )
        return FakeTradeReview(
            operation=operation,
            submitted=True,
            risk_decision=None,
            order_result=result,
        )

    async def sell(self, intent: SellOrderIntent, **kwargs: object) -> FakeTradeReview:
        self.sell_calls.append(intent)
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.LIVE,
            intent=intent,
            order_id=f"{intent.trace_id}-sell",
            side=OrderSide.SELL,
            order_type=intent.order_type,
            price=intent.price,
            requested_size_shares=intent.size_shares,
            matched_shares=Decimal("0"),
            remaining_shares=intent.size_shares,
            notional_usdc=intent.notional_usdc,
            reason="sell_submitted",
            timestamps=ExecutionTimestamps(
                queued_at=now,
                sign_started_at=now,
                signed_at=now,
                submitted_at=now,
                ack_at=now,
            ),
        )
        return FakeTradeReview(
            operation="sell",
            submitted=True,
            risk_decision=FakeRiskDecision(passed=True),
            order_result=result,
        )


def _market() -> Market:
    return Market(
        condition_id="condition-500m",
        market_slug="sample-market-a",
        no_token_id="no-token-500m",
        yes_token_id="yes-token-500m",
        event_id="event-1",
        event_title="Sample Market A",
        event_slug="sample-event-a",
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        fees_enabled=True,
        maker_base_fee_bps=0,
        taker_base_fee_bps=100,
        fee_rate_bps=125,
        fee_rate_updated_at=datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc),
        category="Crypto",
        matched_keywords=("sample", "market", "threshold"),
        trading_status=TradingStatus.ELIGIBLE,
    )


def _orderbook(market: Market) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        token_id=market.no_token_id,
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.59"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.59"), size=Decimal("200")),),
        received_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        best_bid_size=Decimal("100"),
        best_ask_size=Decimal("200"),
        tick_size=market.tick_size,
    )


def _reconcile_result(market: Market) -> object:
    action = ReconcileAction(
        action_type=ReconcileActionType.CANCEL_OPEN_BUY,
        trace_id="trace-reconcile",
        condition_id=market.condition_id,
        token_id=market.no_token_id,
        market_slug=market.market_slug,
        reason="open_buy_detected",
        source_order_id="buy-1",
        target_size_shares=Decimal("5"),
    )
    plan = ReconcilePlan(
        trace_id="trace-reconcile",
        generated_at=datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
        market_plans=(
            ReconcileMarketPlan(
                trace_id="trace-reconcile",
                market=market,
                position=None,
                open_buy_orders=(),
                open_sell_orders=(),
                actions=(action,),
                pause_trading=False,
            ),
        ),
        total_actions=1,
        paused_markets=0,
    )
    return SimpleNamespace(
        trace_id="trace-reconcile",
        plan=plan,
        applied_actions=(action,),
        failed_actions=(),
    )


def _build_runtime(*, ready: bool = True) -> SimpleNamespace:
    market = _market()
    settings = Settings(
        portfolio_budget_usdc=Decimal("100"),
        max_order_usdc=Decimal("25"),
        max_market_usdc=Decimal("50"),
        max_total_usdc=Decimal("100"),
        min_liquidity_usdc=Decimal("5"),
        max_spread=Decimal("0.10"),
        max_open_orders=10,
        wallet_private_key=SecretStr("super-secret"),
    )
    registry = MarketRegistry()
    registry.upsert(market)
    account_state_store = AccountStateStore()
    account_state_store.update_balances(balance_usdc=Decimal("100"), allowance_usdc=Decimal("90"))
    account_state_store.upsert_position(
        Position(
            condition_id=market.condition_id,
            token_id=market.no_token_id,
            market_slug=market.market_slug,
            shares=Decimal("5"),
            cost_usdc=Decimal("3"),
        )
    )
    account_state_store.upsert_order(
        OrderRecord(
            trace_id="trace-buy",
            condition_id=market.condition_id,
            token_id=market.no_token_id,
            market_slug=market.market_slug,
            side=OrderSide.BUY,
            order_type=OrderType.FAK,
            price=Decimal("0.60"),
            amount_usdc=Decimal("10"),
            order_id="buy-1",
            status=OrderStatus.LIVE,
            remaining_shares=Decimal("5"),
            idempotency_key="buy-1",
            reason="open_buy_detected",
        )
    )
    account_state_store.upsert_order(
        OrderRecord(
            trace_id="trace-sell",
            condition_id=market.condition_id,
            token_id=market.no_token_id,
            market_slug=market.market_slug,
            side=OrderSide.SELL,
            order_type=OrderType.GTC,
            price=Decimal("0.70"),
            size_shares=Decimal("5"),
            order_id="sell-1",
            status=OrderStatus.LIVE,
            remaining_shares=Decimal("5"),
            idempotency_key="sell-1",
            reason="existing_sell",
        )
    )
    account_state_store.record_fill(
        Fill(
            trace_id="trace-fill",
            event_type="trade_confirmed",
            market_slug=market.market_slug,
            condition_id=market.condition_id,
            token_id=market.no_token_id,
            order_id="sell-1",
            trade_id="trade-1",
            side="SELL",
            price=Decimal("0.70"),
            size=Decimal("5"),
            notional_usdc=Decimal("3.5"),
            confirmed_at=datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc),
        )
    )
    account_state_store.mark_user_ws_connected(ready)
    if ready:
        account_state_store.mark_reconciled(datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc))

    event_bus = EventBus()
    orderbook = _orderbook(market)
    fake_market_ws_worker = FakeMarketWsWorker({market.no_token_id: orderbook})
    readiness = FakeConfigReadiness(ready_to_trade=True)
    runtime_readiness = ReadinessSnapshot(
        phase=RuntimePhase.TRADING_ENABLED if ready else RuntimePhase.RECOVERING_SNAPSHOT,
        live=True,
        ready=ready,
        automatic_trading_enabled=ready,
        config_ready=True,
        db_ready=True,
        trading_client_ready=True,
        market_ws_connected=True,
        user_ws_connected=ready,
        reconcile_fresh=ready,
        outbox_backlog_ok=True,
        low_priority_paused=False,
        blocking_reasons=() if ready else ("user_ws_not_connected", "reconcile_pending"),
        warnings=(),
        last_reconcile_at=account_state_store.snapshot().last_reconcile_at,
    )
    runtime_snapshot = RuntimeSnapshot(
        phase=RuntimePhase.TRADING_ENABLED if ready else RuntimePhase.RECOVERING_SNAPSHOT,
        automatic_trading_enabled=ready,
        low_priority_paused=False,
        live=True,
        status_reason="trading_enabled" if ready else "recovering_snapshot",
        manual_pause_reason=None,
        degraded_reason=None,
        readiness=runtime_readiness,
        settings_readiness=readiness.as_dict(),
        queue_depths=event_bus.snapshot(),
        scheduler=None,
        worker_health=(),
        account=account_state_store.snapshot(),
        market_ws={"connected": True, "subscribed_count": 1},
        user_ws={"connected": ready, "last_error": None if ready else "disconnected"},
        reconcile={
            "last_completed_at": (
                None if account_state_store.snapshot().last_reconcile_at is None
                else account_state_store.snapshot().last_reconcile_at.isoformat()
            ),
            "last_status": "ok" if ready else "pending",
        },
        persistence=FakePersistenceSnapshot(outbox_depth=0),
        metrics={
            "gauges": {"entry_signal_to_submit_ms": 42},
            "queue_depths": {"trading_queue_depth": 0},
        },
    )
    runtime = SimpleNamespace(
        settings=settings,
        readiness=readiness,
        registry=registry,
        gamma_client=FakeGammaClient(),
        clob_client=FakeClobClient(),
        data_client=FakeDataClient(),
        account_state_store=account_state_store,
        market_ws_worker=fake_market_ws_worker,
        event_bus=event_bus,
        persistence_worker=SimpleNamespace(snapshot=lambda: FakePersistenceSnapshot(outbox_depth=0)),
        supervisor=FakeSupervisor(runtime_snapshot),
        strategy_service=FakeStrategyService(),
        trading_service=FakeTradingService(),
        reconcile_worker=FakeReconcileWorker(_reconcile_result(market)),
        bootstrap_summary={"loaded_reference": {"markets": 1, "positions": 1}},
        db_session_factory=None,
    )
    return runtime


def test_admin_api_exposes_hot_state_and_readiness_routes() -> None:
    runtime = _build_runtime(ready=True)
    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        runtime_payload = client.get("/runtime").json()
        workers = client.get("/workers").json()
        metrics = client.get("/metrics").json()
        markets = client.get("/markets").json()
        market_detail = client.get("/markets/detail", params={"market_slug": "sample-market-a"}).json()
        market_orderbook = client.get("/markets/orderbook", params={"market_slug": "sample-market-a"}).json()
        market_midpoint = client.get("/markets/midpoint", params={"market_slug": "sample-market-a"}).json()
        market_positions = client.get(
            "/markets/positions",
            params={
                "condition_id": "0x" + "1" * 64,
                "address": "0x1111111111111111111111111111111111111111",
                "status": "OPEN",
                "sort_by": "TOTAL_PNL",
                "sort_direction": "DESC",
                "limit": 50,
                "offset": 10,
            },
        ).json()
        market_holders = client.get(
            "/markets/holders",
            params={
                "condition_id": "0x" + "1" * 64,
                "limit": 20,
                "min_balance": 1,
            },
        ).json()
        market_prices_history = client.get(
            "/markets/prices-history",
            params={
                "token_id": "no-token-500m",
                "start_ts": 1704100800,
                "end_ts": 1704104400,
                "interval": "1h",
                "fidelity": 60,
            },
        ).json()
        profile_detail = client.get(
            "/profiles/detail",
            params={"address": "0x1111111111111111111111111111111111111111"},
        ).json()
        profile_value = client.get(
            "/profiles/value",
            params={
                "address": "0x1111111111111111111111111111111111111111",
                "condition_id": "0x" + "1" * 64,
            },
        ).json()
        profile_search = client.get(
            "/profiles/search",
            params={"q": "market", "limit": 10, "page": 2},
        ).json()
        profile_activity = client.get(
            "/profiles/activity",
            params={
                "address": "0x1111111111111111111111111111111111111111",
                "limit": 50,
                "offset": 10,
                "condition_id": "0x" + "1" * 64,
                "type": "TRADE",
                "start": 1704000000,
                "end": 1704200000,
                "sort_by": "TIMESTAMP",
                "sort_direction": "DESC",
                "side": "SELL",
            },
        ).json()
        profile_trades = client.get(
            "/profiles/trades",
            params={
                "address": "0x1111111111111111111111111111111111111111",
                "limit": 25,
                "offset": 5,
                "condition_id": "0x" + "1" * 64,
                "side": "SELL",
                "taker_only": "false",
                "filter_type": "CASH",
                "filter_amount": "10",
            },
        ).json()
        profile_positions = client.get(
            "/profiles/positions",
            params={
                "address": "0x1111111111111111111111111111111111111111",
                "limit": 50,
                "offset": 10,
                "condition_id": "0x" + "1" * 64,
                "size_threshold": "2",
                "redeemable": "false",
                "mergeable": "false",
                "sort_by": "TOKENS",
                "sort_direction": "DESC",
                "title": "Crypto",
            },
        ).json()
        profile_closed_positions = client.get(
            "/profiles/closed-positions",
            params={
                "address": "0x1111111111111111111111111111111111111111",
                "limit": 10,
                "offset": 5,
                "condition_id": "0x" + "2" * 64,
                "sort_by": "REALIZEDPNL",
                "sort_direction": "DESC",
                "title": "Crypto",
            },
        ).json()
        orders = client.get("/orders").json()
        hot_positions = client.get("/positions").json()
        fills = client.get("/fills").json()
        portfolio = client.get("/portfolio").json()

        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        assert ready.status_code == 200
        assert ready.json()["ready_to_trade"] is True
        assert ready.json()["phase"] == "trading_enabled"

        assert runtime_payload["registry"]["market_count"] == 1
        assert runtime_payload["settings"]["wallet_private_key"] == "***"
        assert runtime_payload["readiness"]["ready"] is True
        assert runtime_payload["markets"][0]["orderbook"]["best_ask"] == "0.59"
        assert runtime_payload["markets"][0]["market"]["market_slug"] == "sample-market-a"
        assert runtime_payload["markets"][0]["market"]["fees"]["taker_base_fee_bps"] == 100
        assert runtime_payload["markets"][0]["market"]["fees"]["fee_rate_bps"] == 125
        assert workers["phase"] == "trading_enabled"
        assert isinstance(workers["workers"], list)
        assert metrics["metrics"]["gauges"]["entry_signal_to_submit_ms"] == 42

        assert markets["total"] == 1
        assert markets["items"][0]["market"]["condition_id"] == "condition-500m"
        assert markets["items"][0]["market"]["fees"]["enabled"] is True
        assert markets["items"][0]["market"]["fees"]["maker_base_fee_bps"] == 0
        assert markets["items"][0]["market"]["fees"]["fee_rate_updated_at"] == "2026-01-01T12:02:00+00:00"
        assert markets["items"][0]["entry_price_touched"] is True
        assert market_detail["market"]["condition_id"] == "condition-500m"
        assert market_detail["market"]["market_slug"] == "sample-market-a"
        assert market_orderbook["token_id"] == "no-token-500m"
        assert market_orderbook["source"] == "hot"
        assert market_orderbook["orderbook"]["best_bid"] == "0.55"
        assert market_orderbook["orderbook"]["best_ask"] == "0.59"
        assert market_midpoint["token_id"] == "no-token-500m"
        assert market_midpoint["source"] == "hot"
        assert market_midpoint["midpoint"] == "0.57"
        assert market_midpoint["spread"] == "0.04"
        assert market_positions["condition_id"] == "0x" + "1" * 64
        assert market_positions["address"] == "0x1111111111111111111111111111111111111111"
        assert market_positions["items"][0]["token_id"] == "no-token-500m"
        assert market_positions["items"][0]["positions"][0]["current_value"] == "3"
        assert market_positions["items"][0]["positions"][0]["total_pnl"] == "0.6"
        assert runtime.data_client.market_position_calls[0]["condition_id"] == "0x" + "1" * 64
        assert runtime.data_client.market_position_calls[0]["status"] == "OPEN"
        assert runtime.data_client.market_position_calls[0]["sort_by"] == "TOTAL_PNL"
        assert market_holders["condition_id"] == "0x" + "1" * 64
        assert market_holders["items"][0]["token_id"] == "no-token-500m"
        assert market_holders["items"][0]["holders"][0]["amount"] == "25"
        assert runtime.data_client.holder_calls[0]["market_ids"] == ("0x" + "1" * 64,)
        assert runtime.data_client.holder_calls[0]["limit"] == 20
        assert runtime.data_client.holder_calls[0]["min_balance"] == 1
        assert market_prices_history["token_id"] == "no-token-500m"
        assert market_prices_history["interval"] == "1h"
        assert market_prices_history["fidelity"] == 60
        assert market_prices_history["history"][0]["timestamp"] == "2024-01-01T09:20:00+00:00"
        assert market_prices_history["history"][1]["price"] == "0.54"
        assert runtime.clob_client.history_calls[0]["token_id"] == "no-token-500m"
        assert runtime.clob_client.history_calls[0]["start_ts"] == 1704100800.0
        assert runtime.clob_client.history_calls[0]["end_ts"] == 1704104400.0
        assert profile_detail["name"] == "Market Watcher"
        assert profile_detail["profile_image"] == "https://example.com/profile.png"
        assert profile_detail["x_username"] == "marketwatcher"
        assert profile_detail["users"][0]["id"] == "user-1"
        assert profile_value["address"] == "0x1111111111111111111111111111111111111111"
        assert profile_value["condition_id"] == "0x" + "1" * 64
        assert profile_value["value"] == "123.45"
        assert runtime.data_client.value_calls[0]["market_ids"] == ("0x" + "1" * 64,)
        assert profile_search["limit"] == 10
        assert profile_search["page"] == 2
        assert profile_search["has_more"] is False
        assert profile_search["total_results"] == 1
        assert profile_search["items"][0]["profile_id"] == "profile-1"
        assert profile_search["items"][0]["profile_image_optimized"] == "https://example.com/profile-optimized.png"
        assert runtime.gamma_client.search_calls[0]["query"] == "market"
        assert runtime.gamma_client.search_calls[0]["limit_per_type"] == 10
        assert runtime.gamma_client.search_calls[0]["page"] == 2
        assert profile_activity["limit"] == 50
        assert profile_activity["offset"] == 10
        assert profile_activity["items"][0]["type"] == "TRADE"
        assert profile_activity["items"][0]["transaction_hash"] == "0xtrade1"
        assert profile_activity["items"][0]["profile_image_optimized"] == "https://example.com/profile-optimized.png"
        assert runtime.data_client.calls[0]["market_ids"] == ("0x" + "1" * 64,)
        assert runtime.data_client.calls[0]["activity_types"] == ("TRADE",)
        assert runtime.data_client.calls[0]["sort_by"] == "TIMESTAMP"
        assert runtime.data_client.calls[0]["sort_direction"] == "DESC"
        assert runtime.data_client.calls[0]["side"] == "SELL"
        assert profile_trades["limit"] == 25
        assert profile_trades["offset"] == 5
        assert profile_trades["items"][0]["trade_id"] == "0xtrade2"
        assert profile_trades["items"][0]["token_id"] == "no-token-500m"
        assert profile_trades["items"][0]["size"] == "5"
        assert profile_trades["items"][0]["notional_usdc"] == "3.5"
        assert profile_trades["items"][0]["profile_image_optimized"] == "https://example.com/profile-optimized.png"
        assert runtime.data_client.trade_calls[0]["market_ids"] == ("0x" + "1" * 64,)
        assert runtime.data_client.trade_calls[0]["side"] == "SELL"
        assert runtime.data_client.trade_calls[0]["taker_only"] is False
        assert runtime.data_client.trade_calls[0]["filter_type"] == "CASH"
        assert runtime.data_client.trade_calls[0]["filter_amount"] == Decimal("10")
        assert profile_positions["limit"] == 50
        assert profile_positions["offset"] == 10
        assert profile_positions["items"][0]["token_id"] == "no-token-500m"
        assert profile_positions["items"][0]["shares"] == "5"
        assert profile_positions["items"][0]["current_value"] == "3"
        assert profile_positions["items"][0]["outcome"] == "No"
        assert runtime.data_client.position_calls[0]["market_ids"] == ("0x" + "1" * 64,)
        assert runtime.data_client.position_calls[0]["size_threshold"] == Decimal("2")
        assert runtime.data_client.position_calls[0]["sort_by"] == "TOKENS"
        assert runtime.data_client.position_calls[0]["title"] == "Crypto"
        assert profile_closed_positions["limit"] == 10
        assert profile_closed_positions["offset"] == 5
        assert profile_closed_positions["items"][0]["token_id"] == "yes-token-1b"
        assert profile_closed_positions["items"][0]["realized_pnl"] == "2.5"
        assert profile_closed_positions["items"][0]["timestamp"] == "2024-01-01T09:20:00+00:00"
        assert runtime.data_client.closed_position_calls[0]["market_ids"] == ("0x" + "2" * 64,)
        assert runtime.data_client.closed_position_calls[0]["sort_by"] == "REALIZEDPNL"
        assert runtime.data_client.closed_position_calls[0]["title"] == "Crypto"

        assert orders["total"] == 2
        assert orders["items"][0]["order_id"] == "buy-1"
        assert orders["items"][1]["side"] == "SELL"

        assert hot_positions["total"] == 1
        assert hot_positions["items"][0]["shares"] == "5"

        assert fills["total"] == 1
        assert fills["items"][0]["trade_id"] == "trade-1"

        assert portfolio["allow_new_buys"] is True
        assert portfolio["markets_tracked"] == 1
        assert portfolio["position_count"] == 1


def test_admin_api_supports_reconcile_and_cancel_replace_sell_routes() -> None:
    runtime = _build_runtime(ready=True)
    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        reconcile_response = client.post(
            "/operations/reconcile",
            json={
                "trace_id": "trace-manual-reconcile",
                "condition_ids": ["condition-500m"],
            },
        )
        cancel_replace_response = client.post(
            "/orders/cancel-replace-sell",
            json={
                "market_slug": "sample-market-a",
                "new_price": "0.70",
                "operator": "manual",
                "reason": "admin_reprice",
                "trace_id": "trace-reprice",
            },
        )

        assert reconcile_response.status_code == 200
        reconcile_payload = reconcile_response.json()
        assert reconcile_payload["status"] == "ok"
        assert reconcile_payload["plan"]["total_actions"] == 1
        assert reconcile_payload["plan"]["market_plans"][0]["actions"][0]["action_type"] == "cancel_open_buy"
        assert runtime.reconcile_worker.calls == [("trace-manual-reconcile", ("condition-500m",))]

        assert cancel_replace_response.status_code == 200
        cancel_replace_payload = cancel_replace_response.json()
        assert cancel_replace_payload["status"] == "ok"
        assert cancel_replace_payload["cancelled_orders"][0]["order_result"]["status"] == "cancelled"
        assert cancel_replace_payload["replace_order_submitted"]["status"] == "live"
        assert cancel_replace_payload["replace_order_submitted"]["price"] == "0.70"
        assert runtime.trading_service.cancel_calls
        assert runtime.trading_service.sell_calls

        updated_portfolio = client.get("/portfolio").json()
        assert updated_portfolio["open_order_count"] == 2


def test_admin_api_supports_fee_filters_and_sorting() -> None:
    runtime = _build_runtime(ready=True)
    runtime.db_session_factory = object()
    second_market = replace(
        _market(),
        condition_id="condition-1b",
        market_slug="sample-market-b",
        no_token_id="no-token-1b",
        yes_token_id="yes-token-1b",
        fee_rate_bps=200,
        taker_base_fee_bps=150,
        maker_base_fee_bps=5,
        fee_rate_updated_at=datetime(2026, 1, 1, 12, 3, 0, tzinfo=timezone.utc),
    )
    runtime.registry.upsert(second_market)
    runtime.market_ws_worker._snapshots[second_market.no_token_id] = _orderbook(second_market)

    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        filtered = client.get(
            "/markets",
            params={
                "fees_enabled": "true",
                "fee_rate_bps_min": 150,
                "taker_base_fee_bps_min": 120,
                "sort_by": "fee_rate_bps",
                "sort_direction": "desc",
            },
        ).json()
        sorted_markets = client.get(
            "/markets",
            params={
                "sort_by": "fee_rate_bps",
                "sort_direction": "desc",
            },
        ).json()

        assert filtered["total"] == 1
        assert filtered["items"][0]["market"]["condition_id"] == "condition-1b"
        assert filtered["items"][0]["market"]["fees"]["fee_rate_bps"] == 200

        assert sorted_markets["total"] == 2
        assert [item["market"]["condition_id"] for item in sorted_markets["items"]] == [
            "condition-1b",
            "condition-500m",
        ]


def test_markets_orderbook_falls_back_to_clob_when_hot_snapshot_missing() -> None:
    runtime = _build_runtime(ready=True)
    runtime.market_ws_worker._snapshots.clear()
    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        payload = client.get(
            "/markets/orderbook",
            params={"token_id": "no-token-500m"},
        ).json()

        assert payload["token_id"] == "no-token-500m"
        assert payload["source"] == "rest"
        assert payload["orderbook"]["last_trade_price"] == "0.54"
        assert runtime.clob_client.orderbook_calls[0]["token_id"] == "no-token-500m"


def test_markets_midpoint_falls_back_to_clob_when_hot_snapshot_missing() -> None:
    runtime = _build_runtime(ready=True)
    runtime.market_ws_worker._snapshots.clear()
    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        payload = client.get(
            "/markets/midpoint",
            params={"token_id": "no-token-500m"},
        ).json()

        assert payload["token_id"] == "no-token-500m"
        assert payload["source"] == "rest"
        assert payload["midpoint"] == "0.57"
        assert runtime.clob_client.midpoint_calls[0]["token_id"] == "no-token-500m"


def test_admin_ready_route_reports_blockers_when_runtime_is_not_ready() -> None:
    runtime = _build_runtime(ready=False)
    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        ready = client.get("/ready")
        runtime_payload = client.get("/runtime").json()

        assert ready.status_code == 200
        assert ready.json()["ready_to_trade"] is False
        assert ready.json()["blocking_issues"]
        assert "user_ws_not_connected" in ready.json()["runtime"]["blocking_reasons"]
        assert runtime_payload["runtime"]["ready_to_trade"] is False
        assert runtime_payload["readiness"]["ready"] is False


def test_admin_api_exposes_audit_allocations_outbox_and_order_id_filter(monkeypatch) -> None:
    runtime = _build_runtime(ready=True)
    runtime.db_session_factory = object()

    audit_events = (
        AuditEvent(
            event_type="order_cancelled",
            trace_id="trace-audit",
            event_id="audit-1",
            market_slug="sample-market-a",
            condition_id="condition-500m",
            token_id="no-token-500m",
            order_id="buy-1",
            status="cancelled",
            reason="manual_cancel",
        ),
    )
    allocations = (
        Allocation(
            condition_id="condition-500m",
            market_slug="sample-market-a",
            token_id="no-token-500m",
            target_budget_usdc=Decimal("50"),
            buy_budget_usdc=Decimal("25"),
            current_exposure_usdc=Decimal("10"),
            released_budget_usdc=Decimal("5"),
            reason="equal_weight",
            release_reason="no_fill",
            idempotency_key="alloc-1",
        ),
    )
    outbox_events = (
        OutboxEvent(
            trace_id="trace-outbox",
            event_type="order_submitted",
            idempotency_key="outbox-1",
            event_id="outbox-event-1",
            market_slug="sample-market-a",
            condition_id="condition-500m",
            token_id="no-token-500m",
            reason="submit",
            priority="P1",
            payload={"order_id": "buy-1"},
        ),
    )

    async def _list_audit_events_snapshot(
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        event_type: str | None = None,
    ) -> RepositoryPage[AuditEvent]:
        items = [
            event
            for event in audit_events
            if (trace_id is None or event.trace_id == trace_id)
            and (event_type is None or event.event_title == event_type)
        ]
        return RepositoryPage(items=tuple(items[offset : offset + limit]), total=len(items), limit=limit, offset=offset)

    async def _list_allocations_snapshot(
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
        condition_id: str | None = None,
        token_id: str | None = None,
        market_slug: str | None = None,
    ) -> RepositoryPage[Allocation]:
        del trace_id
        items = [
            allocation
            for allocation in allocations
            if (condition_id is None or allocation.condition_id == condition_id)
            and (token_id is None or allocation.token_id == token_id)
            and (market_slug is None or allocation.market_slug == market_slug)
        ]
        return RepositoryPage(items=tuple(items[offset : offset + limit]), total=len(items), limit=limit, offset=offset)

    async def _list_pending_snapshot(
        *,
        limit: int = 100,
        offset: int = 0,
        trace_id: str | None = None,
    ) -> RepositoryPage[OutboxEvent]:
        items = [
            event
            for event in outbox_events
            if trace_id is None or event.trace_id == trace_id
        ]
        return RepositoryPage(items=tuple(items[offset : offset + limit]), total=len(items), limit=limit, offset=offset)

    async def _fake_with_repositories(self, callback):
        repositories = SimpleNamespace(
            audit=SimpleNamespace(list_audit_events_snapshot=_list_audit_events_snapshot),
            allocation=SimpleNamespace(list_allocations_snapshot=_list_allocations_snapshot),
            outbox=SimpleNamespace(list_pending_snapshot=_list_pending_snapshot),
            market=SimpleNamespace(
                get_by_condition_id=lambda condition_id: None,
                get_by_market_slug=lambda market_slug: None,
                get_by_no_token_id=lambda token_id: None,
            ),
            order=None,
            fill=None,
            position=None,
        )
        return await callback(repositories)

    monkeypatch.setattr(AdminService, "_with_repositories", _fake_with_repositories)

    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        audit_payload = client.get(
            "/audit-events",
            params={"trace_id": "trace-audit", "event_type": "order_cancelled"},
        ).json()
        allocations_payload = client.get(
            "/allocations",
            params={"condition_id": "condition-500m"},
        ).json()
        outbox_payload = client.get(
            "/outbox/pending",
            params={"trace_id": "trace-outbox"},
        ).json()
        filtered_orders = client.get(
            "/orders",
            params={"order_id": "buy-1"},
        ).json()

        assert audit_payload["total"] == 1
        assert audit_payload["items"][0]["event_id"] == "audit-1"
        assert audit_payload["items"][0]["event_title"] == "order_cancelled"

        assert allocations_payload["total"] == 1
        assert allocations_payload["items"][0]["idempotency_key"] == "alloc-1"
        assert allocations_payload["items"][0]["target_budget_usdc"] == "50"

        assert outbox_payload["total"] == 1
        assert outbox_payload["items"][0]["idempotency_key"] == "outbox-1"
        assert outbox_payload["items"][0]["priority"] == 1

        assert filtered_orders["total"] == 1
        assert filtered_orders["items"][0]["order_id"] == "buy-1"


def test_profiles_detail_returns_404_when_upstream_profile_is_missing() -> None:
    runtime = _build_runtime(ready=True)
    runtime.gamma_client = FakeGammaClient(
        error=PolymarketResponseError(
            "profile not found",
            operation="gamma.get_public_profile",
            status_code=404,
        )
    )
    app = create_app(runtime=runtime, admin_service=AdminService())

    with TestClient(app) as client:
        response = client.get(
            "/profiles/detail",
            params={"address": "0x1111111111111111111111111111111111111111"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "profile not found"
