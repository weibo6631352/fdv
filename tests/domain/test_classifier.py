from __future__ import annotations

from fdv_trader.domain.classifier import MarketClassifier


def test_classifier_accepts_crypto_fdv_500m_market() -> None:
    result = MarketClassifier().classify(
        {
            "category": "Crypto",
            "event_title": "Will token FDV reach a threshold?",
            "question": "Will this project hit $500M FDV?",
        }
    )

    assert result.accepted

