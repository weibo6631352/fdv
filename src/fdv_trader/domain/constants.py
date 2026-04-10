from __future__ import annotations

from decimal import Decimal

ENTRY_NO_PRICE_MAX = Decimal("0.60")
EXIT_NO_PRICE = Decimal("0.70")

CRYPTO_KEYWORDS = frozenset(("crypto", "cryptocurrency"))
EXCLUDED_THRESHOLD_KEYWORDS = frozenset(("150m", "$150m", "300m", "$300m", "800m", "$800m", "1b", "$1b"))

