from __future__ import annotations

from fdv_trader.domain.classifier import MarketClassifier


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
