from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

from fdv_trader.domain.allocation import Allocation, AllocationPlan
from fdv_trader.domain.market import Market
from fdv_trader.domain.order import Order
from fdv_trader.domain.orderbook import OrderbookSnapshot
from fdv_trader.domain.position import Position
from fdv_trader.runtime.account_state import AccountSnapshot


class StrategyAction(StrEnum):
    SKIP = "skip"
    BUY = "buy"
    SELL = "sell"
    CANCEL = "cancel"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class StrategySpec:
    name: str
    version: str = "1"
    description: str = ""
    config_type: type[Any] | None = None
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UniverseDecision:
    selected: bool
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def include(
        cls,
        *,
        reason: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> "UniverseDecision":
        return cls(selected=True, reason=reason, metadata=metadata or {})

    @classmethod
    def exclude(
        cls,
        *,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "UniverseDecision":
        return cls(selected=False, reason=reason, metadata=metadata or {})


@dataclass(frozen=True, slots=True)
class StrategyContext:
    trace_id: str
    market: Market | None = None
    orderbook: OrderbookSnapshot | None = None
    account_snapshot: AccountSnapshot | None = None
    position: Position | None = None
    open_orders: tuple[Order, ...] = ()
    now: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    action: StrategyAction
    reason: str = ""
    price: Decimal | None = None
    amount_usdc: Decimal | None = None
    size_shares: Decimal | None = None
    order_id: str | None = None
    market_slug: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def skip(
        cls,
        *,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StrategyDecision":
        return cls(
            action=StrategyAction.SKIP,
            reason=reason,
            metadata=metadata or {},
        )

    @classmethod
    def buy(
        cls,
        *,
        reason: str,
        price: Decimal,
        amount_usdc: Decimal,
        market_slug: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StrategyDecision":
        return cls(
            action=StrategyAction.BUY,
            reason=reason,
            price=price,
            amount_usdc=amount_usdc,
            market_slug=market_slug,
            metadata=metadata or {},
        )

    @classmethod
    def sell(
        cls,
        *,
        reason: str,
        price: Decimal,
        size_shares: Decimal,
        market_slug: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StrategyDecision":
        return cls(
            action=StrategyAction.SELL,
            reason=reason,
            price=price,
            size_shares=size_shares,
            market_slug=market_slug,
            metadata=metadata or {},
        )

    @classmethod
    def cancel(
        cls,
        *,
        reason: str,
        order_id: str,
        market_slug: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StrategyDecision":
        return cls(
            action=StrategyAction.CANCEL,
            reason=reason,
            order_id=order_id,
            market_slug=market_slug,
            metadata=metadata or {},
        )

    @classmethod
    def replace(
        cls,
        *,
        reason: str,
        order_id: str,
        price: Decimal,
        size_shares: Decimal,
        market_slug: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "StrategyDecision":
        return cls(
            action=StrategyAction.REPLACE,
            reason=reason,
            price=price,
            size_shares=size_shares,
            order_id=order_id,
            market_slug=market_slug,
            metadata=metadata or {},
        )


@dataclass(frozen=True, slots=True)
class EntrySizing:
    allocation_plan: AllocationPlan
    allocation: Allocation | None = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def eligible_market_count(self) -> int:
        return self.allocation_plan.eligible_market_count


@dataclass(frozen=True, slots=True)
class RecoveryReplaceRequest:
    order_id: str
    new_price: Decimal
    size_shares: Decimal
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    reason: str = ""
    target_sell_size_shares: Decimal = Decimal("0")
    cancel_order_ids: tuple[str, ...] = ()
    replace_requests: tuple[RecoveryReplaceRequest, ...] = ()
    pause_market: bool = False
    pause_reason: str = ""

    @property
    def has_actions(self) -> bool:
        return bool(self.cancel_order_ids or self.replace_requests or self.pause_market)
