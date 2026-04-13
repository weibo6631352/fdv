from __future__ import annotations

from polymarket_trader.domain.classifier import ClassificationRejectReason, MarketClassifier


def test_classifier_accepts_market_with_required_trading_fields() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Sports",
            "event_title": "Any event title is acceptable at parser level",
            "question": "Any market question is acceptable at parser level",
            "market_slug": "sample-market-a",
            "condition_id": "condition",
            "yes_token_id": "yes",
            "no_token_id": "no",
            "tick_size": "0.01",
            "min_order_size": "1",
        }
    )

    assert result.accepted


def test_classifier_preserves_generic_text_fields() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Crypto",
            "event_title": "Will this market reach a threshold?",
            "question": "Will this market hit a threshold?",
            "name": "Threshold market",
            "market_slug": "sample-threshold-market",
            "condition_id": "condition",
            "yes_token_id": "yes",
            "no_token_id": "no",
            "tick_size": "0.01",
            "min_order_size": "1",
        }
    )

    assert result.accepted
    market = result.to_market()
    assert market.event_title == "Will this market reach a threshold?"
    assert market.market_question == "Will this market hit a threshold?"
    assert market.market_name == "Threshold market"


def test_classifier_rejects_missing_required_identifiers() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Sports",
            "event_title": "Title",
            "question": "Question",
            "market_slug": "sample-market-a",
            "condition_id": "condition",
            "no_token_id": "no",
            "tick_size": "0.01",
            "min_order_size": "1",
        }
    )

    assert not result.accepted
    assert result.reject_reason == ClassificationRejectReason.MISSING_TRADING_CONDITIONS


def test_classifier_rejects_missing_tick_and_min_order_size() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Crypto",
            "event_title": "Title",
            "question": "Question",
            "market_slug": "token-market",
            "condition_id": "condition",
            "yes_token_id": "yes",
            "no_token_id": "no",
        }
    )

    assert not result.accepted
    assert result.reject_reason == ClassificationRejectReason.MISSING_TRADING_CONDITIONS
