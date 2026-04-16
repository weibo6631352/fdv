from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.domain.orderbook import OrderbookSnapshot, PriceLevel
from polymarket_trader.domain.position import Position
from polymarket_trader.runtime.account_state import AccountSnapshot
from strategy_sdk.models import EntryCandidate, EntrySizing, StrategyAction, StrategyContext
from strategies.current.strategy import build_strategy as build_current_strategy


def test_strategy_contract_positive_path() -> None:
    strategy = build_current_strategy()
    assert strategy.build_discovery_queries()
    market = Market(
        condition_id="condition-current",
        market_slug="slug-current",
        no_token_id="no-current",
        yes_token_id="yes-current",
        event_title="Will token FDV reach a threshold?",
        market_question="Will this project hit $500M FDV?",
        category="Crypto",
        trading_status=TradingStatus.ELIGIBLE,
    )

    received_at = datetime.now(timezone.utc)
    orderbook = OrderbookSnapshot(
        token_id=market.no_token_id,
        best_bid=Decimal("0.55"),
        best_ask=Decimal("0.60"),
        bids=(PriceLevel(price=Decimal("0.55"), size=Decimal("100")),),
        asks=(PriceLevel(price=Decimal("0.60"), size=Decimal("100")),),
        received_at=received_at,
        market_slug=market.market_slug,
        condition_id=market.condition_id,
        best_bid_size=Decimal("100"),
        best_ask_size=Decimal("100"),
        tick_size=market.tick_size,
    )
    position = Position(
        condition_id=market.condition_id,
        token_id=market.no_token_id,
        shares=Decimal("10"),
        cost_usdc=Decimal("5"),
        market_slug=market.market_slug,
    )
    account_snapshot = AccountSnapshot(
        positions=(position,),
        paused_markets=(),
    )

    universe = strategy.select_market(market)
    assert universe.selected is True

    sizing = strategy.size_entry(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            token_id=market.no_token_id,
            orderbook=orderbook,
            entry_candidates=(
                EntryCandidate(
                    market=market,
                    token_id=market.no_token_id,
                    orderbook=orderbook,
                ),
            ),
            metadata={
                "portfolio_budget_usdc": Decimal("100"),
                "available_usdc": Decimal("100"),
                "max_order_usdc": Decimal("100"),
                "max_market_usdc": Decimal("100"),
                "max_total_usdc": Decimal("100"),
            },
        )
    )
    assert isinstance(sizing, EntrySizing)
    assert sizing.allocation is not None
    assert sizing.allocation.buy_budget_usdc > Decimal("0")

    entry = strategy.decide_entry(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            token_id=market.no_token_id,
            orderbook=orderbook,
            metadata={"amount_usdc": Decimal("10")},
        )
    )
    assert entry.action == StrategyAction.BUY
    assert entry.amount_usdc == Decimal("10")

    exit_decision = strategy.decide_exit(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            position=position,
        )
    )
    assert exit_decision.action == StrategyAction.SELL

    recovery = strategy.decide_recovery(
        StrategyContext(
            trace_id="trace-contract",
            market=market,
            position=position,
            account_snapshot=account_snapshot,
        )
    )
    assert len(recovery.actions) == 1
    assert recovery.actions[0].action == StrategyAction.SELL
    assert recovery.actions[0].size_shares == Decimal("10")
