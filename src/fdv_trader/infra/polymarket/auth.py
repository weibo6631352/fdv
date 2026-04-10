from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PolymarketCredentials:
    api_key: str
    api_secret: str
    api_passphrase: str
    wallet_private_key: str

