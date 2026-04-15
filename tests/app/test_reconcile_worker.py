from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from polymarket_trader.app.reconcile_service import ReconcileActionType, ReconcileService
from polymarket_trader.app.trading_service import TradingService
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.order import (
    CancelOrderIntent,
    OrderRecord,
    OrderResult,
    OrderResultStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    ReplaceOrderIntent,
    SellOrderIntent,
)
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.domain.position import Position
from polymarket_trader.runtime.account_state import AccountStateStore
from polymarket_trader.runtime.registry import MarketRegistry
from strategy_sdk.models import (
    RecoveryDecision,
    RecoveryReplaceRequest,
    StrategyContext,
    StrategyDecision,
    StrategyRuntimeProfile,
    StrategySpec,
    UniverseDecision,
)
from strategies.current.strategy import build_strategy
from polymarket_trader.workers.market_ws_worker import MarketWsWorker
from polymarket_trader.workers.reconcile_worker import ReconcileWorker


class _StubExecutor:
    def __init__(self) -> None:
        self.submitted_intents: list[SellOrderIntent] = []
        self.cancelled_intents: list[CancelOrderIntent] = []
        self.replaced_intents: list[ReplaceOrderIntent] = []

    async def submit(self, intent: SellOrderIntent) -> OrderResult:
        self.submitted_intents.append(intent)
        return OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.LIVE,
            intent=intent,
            side=intent.side,
            order_type=intent.order_type,
            price=intent.price,
            requested_size_shares=intent.size_shares,
            notional_usdc=intent.notional_usdc,
            reason="sell_submitted",
        )

    async def cancel(self, intent: CancelOrderIntent) -> OrderResult:
        self.cancelled_intents.append(intent)
        return OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.CANCELLED,
            intent=intent,
            reason="cancelled",
        )

    async def replace(self, intent: ReplaceOrderIntent) -> OrderResult:
        self.replaced_intents.append(intent)
        return OrderResult(
            trace_id=intent.trace_id,
            condition_id=intent.condition_id,
            token_id=intent.token_id,
            market_slug=intent.market_slug,
            status=OrderResultStatus.LIVE,
            intent=intent,
            price=intent.new_price,
            requested_size_shares=intent.size_shares,
            remaining_shares=intent.size_shares,
            notional_usdc=intent.new_price * intent.size_shares,
            order_id="sell-2",
            reason="sell_replaced",
        )


class _ReplaceRecoveryStrategy:
    @property
    def spec(self) -> StrategySpec:
        return StrategySpec(
            name="replace-recovery",
            capabilities=("universe", "entry", "exit", "recovery"),
        )

    @property
    def runtime_profile(self) -> StrategyRuntimeProfile:
        return StrategyRuntimeProfile()

    def build_discovery_queries(self) -> tuple[object, ...]:
        return ()

    def select_market(self, market: Market) -> UniverseDecision:
        return UniverseDecision.include(reason="selected")

    def size_entry(self, context: StrategyContext):  # pragma: no cover - not used in this test
        raise AssertionError("size_entry should not be called in reconcile replace test")

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:  # pragma: no cover - not used
        raise AssertionError("decide_entry should not be called in reconcile replace test")

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.skip(reason="no_missing_sell")

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        return RecoveryDecision(
            reason="replace_existing_sell",
            target_sell_size_shares=Decimal("5"),
            replace_requests=(
                RecoveryReplaceRequest(
                    order_id="sell-1",
                    new_price=Decimal("0.72"),
                    size_shares=Decimal("5"),
                    reason="repriced",
                ),
            ),
        )


class _StubGammaMarket:
    def __init__(self, market: Market) -> None:
        self.condition_id = market.condition_id
        self.no_token_id = market.no_token_id
        self.market_slug = market.market_slug
        self.clob_enabled = True
        self._market = market

    def to_market(self) -> Market:
        return self._market


class _StubGammaClient:
    def __init__(self, market: Market) -> None:
        self._market = market

    async def list_markets(self, **kwargs: object) -> tuple[_StubGammaMarket, ...]:
        return (_StubGammaMarket(self._market),)


class _StubOrderbookDTO:
    def __init__(self, snapshot: OrderbookSnapshot) -> None:
        self._snapshot = snapshot

    def to_snapshot(self) -> OrderbookSnapshot:
        return self._snapshot


class _StubClobClient:
    has_auth_client = False

    def __init__(self, snapshot: OrderbookSnapshot, fee_rate_bps: int) -> None:
        self._snapshot = snapshot
        self._fee_rate_bps = fee_rate_bps

    async def get_orderbook(self, *args: object, **kwargs: object) -> _StubOrderbookDTO:
        return _StubOrderbookDTO(self._snapshot)

    async def get_fee_rate(self, token_id: str) -> int:
        return self._fee_rate_bps


class _StubPositionsDataClient:
    async def list_positions(self) -> tuple[Position, ...]:
        return ()


class _StubAccountClobClient:
    def __init__(self, *, balance_usdc: Decimal, allowance_usdc: Decimal) -> None:
        self._balance = balance_usdc
        self._allowance = allowance_usdc

    async def list_open_orders(self) -> tuple[OrderRecord, ...]:
        return ()

    async def list_fills(self) -> tuple[object, ...]:
        return ()

    async def get_balance_allowance(self) -> SimpleNamespace:
        return SimpleNamespace(
            balance_usdc=self._balance,
            allowance_usdc=self._allowance,
        )


def test_reconcile_worker_cancels_open_buy_and_backfills_missing_sell() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        market = Market(
            condition_id="condition",
            market_slug="token-500m-fdv",
            no_token_id="token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            event_title="Will token FDV reach a threshold?",
            market_question="Will this project hit $500M FDV?",
            category="Crypto",
            trading_status=TradingStatus.ELIGIBLE,
        )
        registry.upsert(market)

        account_state_store = AccountStateStore()
        account_state_store.upsert_position(
            Position(
                condition_id="condition",
                token_id="token",
                market_slug=market.market_slug,
                shares=Decimal("5"),
                cost_usdc=Decimal("3"),
            )
        )
        account_state_store.upsert_order(
            OrderRecord(
                trace_id="trace-buy",
                condition_id="condition",
                token_id="token",
                market_slug=market.market_slug,
                side=OrderSide.BUY,
                order_type=OrderType.FAK,
                price=Decimal("0.60"),
                amount_usdc=Decimal("3"),
                order_id="buy-1",
                status=OrderStatus.LIVE,
                remaining_shares=Decimal("5"),
                idempotency_key="buy-1",
                reason="open_buy_detected",
            )
        )

        executor = _StubExecutor()
        worker = ReconcileWorker(
            reconcile_service=ReconcileService(strategy_module=build_strategy()),
            registry_snapshot_provider=registry.snapshot,
            account_state_store=account_state_store,
            trading_service=TradingService(executor=executor),
            executor=executor,
        )

        result = await worker.reconcile_once(trace_id="trace-reconcile")

        assert result.plan.has_changes
        action_types = {action.action_type for action in result.plan.market_plans[0].actions}
        assert ReconcileActionType.CANCEL_OPEN_BUY in action_types
        assert ReconcileActionType.SUBMIT_MISSING_SELL in action_types

    asyncio.run(run())


def test_reconcile_worker_refreshes_market_fee_fields() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        current_market = Market(
            condition_id="condition",
            market_slug="token-500m-fdv",
            no_token_id="token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            category="Crypto",
            event_title="Will token FDV reach a threshold?",
            market_question="Will this project hit $500M FDV?",
            trading_status=TradingStatus.ELIGIBLE,
        )
        registry.upsert(current_market)

        refreshed_market = Market(
            condition_id="condition",
            market_slug="token-500m-fdv",
            no_token_id="token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            neg_risk=False,
            fees_enabled=True,
            maker_base_fee_bps=0,
            taker_base_fee_bps=100,
            category="Crypto",
            event_title="Will token FDV reach a threshold?",
            market_question="Will this project hit $500M FDV?",
            trading_status=TradingStatus.ELIGIBLE,
        )
        orderbook_snapshot = OrderbookSnapshot(
            token_id="token",
            best_bid=Decimal("0.55"),
            best_ask=Decimal("0.59"),
            bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
            asks=(PriceLevel(price=Decimal("0.59"), size=Decimal("200")),),
            received_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            market_slug="token-500m-fdv",
            condition_id="condition",
            best_bid_size=Decimal("100"),
            best_ask_size=Decimal("200"),
            tick_size=Decimal("0.01"),
        )

        worker = ReconcileWorker(
            reconcile_service=ReconcileService(strategy_module=build_strategy()),
            registry_snapshot_provider=registry.snapshot,
            registry=registry,
            gamma_client=_StubGammaClient(refreshed_market),
            clob_client=_StubClobClient(orderbook_snapshot, fee_rate_bps=125),
        )

        await worker.reconcile_once(trace_id="trace-reconcile")

        market = registry.get_by_condition_id("condition")
        assert market is not None
        assert market.fees_enabled is True
        assert market.maker_base_fee_bps == 0
        assert market.taker_base_fee_bps == 100
        assert market.fee_rate_bps == 125
        assert market.fee_rate_updated_at is not None

        status = worker.status_snapshot()
        assert status.last_refresh_summary is not None
        assert status.last_refresh_summary.refreshed_fee_rates == 1

    asyncio.run(run())


def test_reconcile_worker_executes_replace_requests_and_keeps_sell_coverage() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        market = Market(
            condition_id="condition",
            market_slug="token-500m-fdv",
            no_token_id="token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            event_title="Will token FDV reach a threshold?",
            market_question="Will this project hit $500M FDV?",
            category="Crypto",
            trading_status=TradingStatus.ELIGIBLE,
        )
        registry.upsert(market)

        account_state_store = AccountStateStore()
        account_state_store.upsert_position(
            Position(
                condition_id="condition",
                token_id="token",
                market_slug=market.market_slug,
                shares=Decimal("5"),
                cost_usdc=Decimal("3"),
                open_sell_shares=Decimal("5"),
            )
        )
        account_state_store.upsert_order(
            OrderRecord(
                trace_id="trace-sell",
                condition_id="condition",
                token_id="token",
                market_slug=market.market_slug,
                side=OrderSide.SELL,
                order_type=OrderType.GTC,
                price=Decimal("0.70"),
                size_shares=Decimal("5"),
                remaining_shares=Decimal("5"),
                notional_usdc=Decimal("3.5"),
                order_id="sell-1",
                status=OrderStatus.LIVE,
                idempotency_key="sell-1",
                reason="open_sell_detected",
            )
        )

        executor = _StubExecutor()
        worker = ReconcileWorker(
            reconcile_service=ReconcileService(strategy_module=_ReplaceRecoveryStrategy()),
            registry_snapshot_provider=registry.snapshot,
            account_state_store=account_state_store,
            trading_service=TradingService(executor=executor),
            executor=executor,
        )

        result = await worker.reconcile_once(trace_id="trace-reconcile-replace")

        assert result.plan.has_changes
        action_types = {action.action_type for action in result.plan.market_plans[0].actions}
        assert action_types == {ReconcileActionType.REPLACE_OPEN_SELL}
        assert len(executor.replaced_intents) == 1
        replace_intent = executor.replaced_intents[0]
        assert replace_intent.order_id == "sell-1"
        assert replace_intent.new_price == Decimal("0.72")
        assert replace_intent.size_shares == Decimal("5")

        snapshot = account_state_store.snapshot()
        position = snapshot.get_position(market.condition_id, market.no_token_id)
        assert position is not None
        assert position.open_sell_shares == Decimal("5")
        open_sell_orders = snapshot.open_sell_orders_for_market(market.condition_id, market.no_token_id)
        assert len(open_sell_orders) == 1
        assert open_sell_orders[0].order_id == "sell-2"
        assert open_sell_orders[0].price == Decimal("0.72")
        assert open_sell_orders[0].remaining_shares == Decimal("5")

    asyncio.run(run())


def test_reconcile_worker_refreshes_account_balance_from_clob_balance_allowance() -> None:
    async def run() -> None:
        account_state_store = AccountStateStore()
        worker = ReconcileWorker(
            reconcile_service=ReconcileService(strategy_module=build_strategy()),
            account_state_store=account_state_store,
            data_client=_StubPositionsDataClient(),
            clob_client=_StubAccountClobClient(
                balance_usdc=Decimal("120"),
                allowance_usdc=Decimal("90"),
            ),
            trading_client=object(),
        )

        summary = await worker._refresh_account_authority(
            trace_id="trace-reconcile",
            markets=(),
        )

        snapshot = account_state_store.snapshot()
        assert snapshot.balance_usdc == Decimal("120")
        assert snapshot.allowance_usdc == Decimal("90")
        assert summary.refreshed_balance is True
        assert summary.refreshed_allowance is True

    asyncio.run(run())


def test_reconcile_worker_prunes_strategy_filtered_market_after_flattening() -> None:
    async def run() -> None:
        registry = MarketRegistry()
        market = Market(
            condition_id="condition",
            market_slug="token-500m-fdv",
            no_token_id="token",
            yes_token_id="yes-token",
            tick_size=Decimal("0.01"),
            min_order_size=Decimal("1"),
            event_title="Will token FDV reach a threshold?",
            market_question="Will this project hit $500M FDV?",
            category="Crypto",
            trading_status=TradingStatus.PAUSED,
            reject_reason="strategy_filtered_out",
        )
        registry.upsert(market)
        account_state_store = AccountStateStore()
        market_ws_worker = MarketWsWorker(registry=registry)
        market_ws_worker.track_market(market)

        worker = ReconcileWorker(
            reconcile_service=ReconcileService(strategy_module=build_strategy()),
            registry_snapshot_provider=registry.snapshot,
            account_state_store=account_state_store,
            registry=registry,
            market_ws_worker=market_ws_worker,
        )

        await worker.reconcile_once(trace_id="trace-prune-filtered")

        assert registry.get_by_condition_id("condition") is None
        assert market_ws_worker.status_snapshot().tracked_token_ids == ()

    asyncio.run(run())
