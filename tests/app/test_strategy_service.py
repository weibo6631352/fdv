from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polymarket_trader.app.strategy_service import StrategyService
from polymarket_trader.domain.allocation import Allocation, AllocationPlan
from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.runtime.registry import MarketRegistry
from strategy_sdk.models import (
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategySpec,
    UniverseDecision,
)
from tests.helpers.markets import build_binary_market


class _CustomSizingStrategy:
    @property
    def spec(self) -> StrategySpec:
        return StrategySpec(
            name="custom",
            capabilities=("universe", "sizing", "entry", "exit", "recovery"),
        )

    def select_market(self, market: Market) -> UniverseDecision:
        return UniverseDecision.include(reason="selected")

    def size_entry(self, context: StrategyContext) -> EntrySizing:
        assert context.market is not None
        allocation = Allocation(
            condition_id=context.market.condition_id,
            target_budget_usdc=Decimal("33"),
            buy_budget_usdc=Decimal("33"),
            market_slug=context.market.market_slug,
            token_id=context.market.require_token_id("NO"),
            reason="custom_sizing",
        )
        return EntrySizing(
            allocation_plan=AllocationPlan(
                trace_id=context.trace_id,
                total_budget_usdc=Decimal("100"),
                allocations=(allocation,),
                reason="custom_sizing",
            ),
            allocation=allocation,
            reason="custom_sizing",
        )

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        assert context.market is not None
        assert context.amount_usdc is not None
        return StrategyDecision.buy(
            reason="custom_entry",
            token_id=context.token_id or context.market.require_token_id("NO"),
            price=Decimal("0.43"),
            amount_usdc=context.amount_usdc,
            market_slug=context.market.market_slug,
        )

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        return StrategyDecision.skip(reason="noop_exit")

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        return RecoveryDecision(reason="noop_recovery")

    def decide_follow_up(self, context: StrategyContext) -> tuple[StrategyDecision, ...]:
        return ()


def test_strategy_service_uses_strategy_sizing_policy() -> None:
    registry = MarketRegistry()
    primary = build_binary_market(
        condition_id="condition-1",
        market_slug="slug-1",
        no_token_id="no-1",
        yes_token_id="yes-1",
        category="Crypto",
        matched_keywords=("threshold", "target"),
        trading_status=TradingStatus.ELIGIBLE,
    )
    secondary = build_binary_market(
        condition_id="condition-2",
        market_slug="slug-2",
        no_token_id="no-2",
        yes_token_id="yes-2",
        category="Crypto",
        matched_keywords=("threshold", "target"),
        trading_status=TradingStatus.ELIGIBLE,
    )
    registry.upsert(primary)
    registry.upsert(secondary)
    snapshots = {
        primary.require_token_id("NO"): _snapshot(primary),
        secondary.require_token_id("NO"): _snapshot(secondary),
    }
    service = StrategyService(
        strategy_module=_CustomSizingStrategy(),
        registry=registry,
        orderbook_reader=snapshots.get,
    )

    plan = service.build_entry_plan(
        condition_id=primary.condition_id,
        token_id=primary.require_token_id("NO"),
        trace_id="trace-custom-sizing",
        portfolio_budget_usdc=Decimal("100"),
        available_usdc=Decimal("100"),
        max_order_usdc=Decimal("100"),
        max_market_usdc=Decimal("100"),
        max_total_usdc=Decimal("100"),
    )

    assert plan.ready_to_trade
    assert plan.allocation is not None
    assert plan.allocation.buy_budget_usdc == Decimal("33")
    assert plan.intent is not None
    assert plan.intent.amount_usdc == Decimal("33")
    assert plan.reason == "custom_sizing"


def _snapshot(market: Market) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        token_id=market.require_token_id("NO"),
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.43"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.43"), size=Decimal("100")),),
        received_at=datetime.now(timezone.utc),
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        best_bid_size=Decimal("100"),
        best_ask_size=Decimal("100"),
        tick_size=market.tick_size,
    )
