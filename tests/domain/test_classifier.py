from __future__ import annotations

from decimal import Decimal

from fdv_trader.domain.classifier import MarketClassifier
from fdv_trader.domain.order import OrderIntent, OrderSide, OrderType
from fdv_trader.domain.risk import RiskManager


def test_classifier_accepts_crypto_fdv_500m_market() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Crypto",
            "event_title": "Will token FDV reach a threshold?",
            "question": "Will this project hit $500M FDV?",
            "market_slug": "token-500m-fdv",
            "condition_id": "condition",
            "yes_token_id": "yes",
            "no_token_id": "no",
            "tick_size": "0.01",
            "min_order_size": "1",
        }
    )

    assert result.accepted


def test_classifier_emits_canonical_keywords_for_risk_gate() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Crypto",
            "event_title": "Will token FDV reach a threshold?",
            "question": "Will this project hit 500 m FDV?",
            "market_slug": "token-fdv-threshold",
            "condition_id": "condition",
            "yes_token_id": "yes",
            "no_token_id": "no",
            "tick_size": "0.01",
            "min_order_size": "1",
        }
    )

    assert result.accepted
    assert "500m" in result.matched_keywords

    decision = RiskManager().check_order_intent(
        OrderIntent(
            trace_id="trace",
            condition_id="condition",
            token_id="no",
            side=OrderSide.BUY,
            order_type=OrderType.FAK,
            price=Decimal("0.60"),
            amount_usdc=Decimal("1"),
        ),
        market=result.to_market(),
    )

    assert decision.passed
