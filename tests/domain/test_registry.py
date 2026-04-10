from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.market import Market, TradingStatus
from fdv_trader.runtime.registry import MarketRegistry


def _market(
    *,
    condition_id: str = "condition",
    market_slug: str = "token-500m-fdv",
    no_token_id: str = "no",
    event_slug: str = "token-event",
) -> Market:
    return Market(
        condition_id=condition_id,
        market_slug=market_slug,
        no_token_id=no_token_id,
        yes_token_id="yes",
        event_id="event-id",
        event_title="Will token FDV reach a threshold?",
        event_slug=event_slug,
        tick_size=Decimal("0.01"),
        min_order_size=Decimal("1"),
        category="Crypto",
        matched_keywords=("crypto", "fdv", "500m"),
        trading_status=TradingStatus.ELIGIBLE,
    )


def test_registry_snapshot_and_indexes_follow_latest_market_state() -> None:
    registry = MarketRegistry()
    market = _market()

    registry.upsert(market)

    assert registry.get_by_condition_id(market.condition_id) == market
    assert registry.get_by_no_token_id(market.no_token_id) == market
    assert registry.get_by_slug(market.market_slug) == market
    assert registry.get_by_slug(market.event_slug or "") == market
    assert registry.snapshot().get_by_condition_id(market.condition_id) == market


def test_registry_updates_indexes_after_token_and_slug_change() -> None:
    registry = MarketRegistry()
    original = _market()
    updated = _market(
        no_token_id="no-v2",
        market_slug="token-500m-fdv-v2",
        event_slug="token-event-v2",
    )

    registry.upsert(original)
    registry.reconcile(updated)

    assert registry.get_by_no_token_id("no") is None
    assert registry.get_by_slug("token-500m-fdv") is None
    assert registry.get_by_slug("token-event") is None
    assert registry.get_by_no_token_id(updated.no_token_id) == updated
    assert registry.get_by_slug(updated.market_slug) == updated
    assert registry.get_by_slug(updated.event_slug or "") == updated
