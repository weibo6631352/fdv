from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fdv_trader.infra.polymarket.schemas import normalize_balance_allowance_payload


def test_normalize_balance_allowance_payload_reads_clob_fields() -> None:
    dto = normalize_balance_allowance_payload(
        {
            "data": {
                "balance": "100.25",
                "allowance": "90.5",
                "updated_at": "2026-01-01T12:00:00+00:00",
            }
        }
    )

    assert dto.balance_usdc == Decimal("100.25")
    assert dto.allowance_usdc == Decimal("90.5")
    assert dto.updated_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
