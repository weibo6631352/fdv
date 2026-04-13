from __future__ import annotations

from enum import StrEnum


class MarketLifecycle(StrEnum):
    DISCOVERED = "discovered"
    CLASSIFIED = "classified"
    WATCHING_ORDERBOOK = "watching_orderbook"
    ENTRY_READY = "entry_ready"
    BUY_SUBMITTING = "buy_submitting"
    BUY_REJECTED = "buy_rejected"
    POSITION_OPEN = "position_open"
    EXIT_ORDER_OPEN = "exit_order_open"
    PAUSED = "paused"
    CLOSED = "closed"
