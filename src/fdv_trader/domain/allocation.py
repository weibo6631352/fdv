from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from fdv_trader.domain.market import Market
from fdv_trader.domain.order import Order, OrderSide, OrderType
from fdv_trader.domain.orderbook import OrderbookSnapshot
from fdv_trader.domain.position import Position


@dataclass(frozen=True, slots=True)
class Allocation:
    condition_id: str
    target_budget_usdc: Decimal
    buy_budget_usdc: Decimal
    market_slug: str | None = None
    token_id: str | None = None
    current_exposure_usdc: Decimal = Decimal("0")
    released_budget_usdc: Decimal = Decimal("0")
    reason: str = ""
    idempotency_key: str | None = None
    release_reason: str = ""


@dataclass(frozen=True, slots=True)
class MarketBuyBudgetChanged:
    condition_id: str
    market_slug: str | None
    token_id: str
    previous_buy_budget_usdc: Decimal
    new_buy_budget_usdc: Decimal
    released_budget_usdc: Decimal
    release_reason: str = ""
    current_exposure_usdc: Decimal = Decimal("0")
    target_budget_usdc: Decimal = Decimal("0")
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AllocationMarketSnapshot:
    market: Market
    orderbook: OrderbookSnapshot | None = None
    position: Position | None = None
    open_orders: tuple[Order, ...] = field(default_factory=tuple)
    classification_passed: bool = True
    classification_reason: str | None = None
    tradable: bool = True
    risk_allowed: bool = True
    market_active: bool = True
    market_open: bool = True
    clob_enabled: bool = True
    resolved: bool = False
    cancelled: bool = False
    archived: bool = False
    liquidity_usdc: Decimal | None = None
    spread: Decimal | None = None
    best_ask: Decimal | None = None
    best_ask_size: Decimal | None = None
    idempotency_key: str | None = None

    @property
    def condition_id(self) -> str:
        return self.market.condition_id

    @property
    def market_slug(self) -> str:
        return self.market.market_slug

    @property
    def token_id(self) -> str:
        return self.market.no_token_id


@dataclass(frozen=True, slots=True)
class AllocationPlan:
    trace_id: str
    total_budget_usdc: Decimal
    allocations: tuple[Allocation, ...] = field(default_factory=tuple)
    budget_changes: tuple[MarketBuyBudgetChanged, ...] = field(default_factory=tuple)
    reason: str = ""

    @property
    def allocated_budget_usdc(self) -> Decimal:
        return sum((allocation.buy_budget_usdc for allocation in self.allocations), Decimal("0"))

    @property
    def released_budget_usdc(self) -> Decimal:
        return sum(
            (allocation.released_budget_usdc for allocation in self.allocations),
            Decimal("0"),
        )

    @property
    def unallocated_budget_usdc(self) -> Decimal:
        remaining = self.total_budget_usdc - self.allocated_budget_usdc
        return remaining if remaining > 0 else Decimal("0")

    @property
    def eligible_market_count(self) -> int:
        return sum(1 for allocation in self.allocations if allocation.target_budget_usdc > 0)

    @classmethod
    def equal_weight(
        cls,
        *,
        trace_id: str,
        portfolio_budget_usdc: Decimal,
        markets: Iterable[AllocationMarketSnapshot],
        available_usdc: Decimal,
        max_order_usdc: Decimal,
        max_market_usdc: Decimal,
        max_total_usdc: Decimal,
        entry_no_price_max: Decimal = Decimal("0.60"),
        min_liquidity_usdc: Decimal = Decimal("0"),
        max_spread: Decimal | None = None,
    ) -> "AllocationPlan":
        market_snapshots = tuple(markets)
        candidate_details: list[dict[str, object]] = []
        allocations: list[Allocation] = []
        budget_changes: list[MarketBuyBudgetChanged] = []
        plan_reason = ""

        total_exposure_usdc = Decimal("0")
        for snapshot in market_snapshots:
            exposure_usdc = current_exposure_usdc(snapshot.position, snapshot.open_orders)
            total_exposure_usdc += exposure_usdc
            skip_reason = _allocation_skip_reason(
                snapshot,
                entry_no_price_max=entry_no_price_max,
                min_liquidity_usdc=min_liquidity_usdc,
                max_spread=max_spread,
            )
            liquidity_usdc = _market_liquidity_usdc(
                snapshot,
                entry_no_price_max=entry_no_price_max,
            )
            depth_usdc = _ask_depth_notional(
                snapshot.orderbook,
                entry_no_price_max=entry_no_price_max,
            )
            hard_capacity_usdc = _market_hard_capacity_usdc(
                snapshot,
                exposure_usdc=exposure_usdc,
                available_usdc=available_usdc,
                max_order_usdc=max_order_usdc,
                max_market_usdc=max_market_usdc,
                entry_no_price_max=entry_no_price_max,
                min_liquidity_usdc=min_liquidity_usdc,
                max_spread=max_spread,
                liquidity_usdc=liquidity_usdc,
                depth_usdc=depth_usdc,
            )

            if skip_reason:
                allocations.append(
                    Allocation(
                        condition_id=snapshot.condition_id,
                        target_budget_usdc=Decimal("0"),
                        buy_budget_usdc=Decimal("0"),
                        market_slug=snapshot.market_slug,
                        token_id=snapshot.token_id,
                        current_exposure_usdc=exposure_usdc,
                        released_budget_usdc=Decimal("0"),
                        reason=skip_reason,
                        idempotency_key=snapshot.idempotency_key,
                        release_reason=skip_reason,
                    )
                )
                continue

            candidate_details.append(
                {
                    "snapshot": snapshot,
                    "exposure_usdc": exposure_usdc,
                    "hard_capacity_usdc": hard_capacity_usdc,
                    "depth_usdc": depth_usdc,
                    "market_min_order_size": snapshot.market.min_order_size,
                    "target_budget_usdc": Decimal("0"),
                    "buy_budget_usdc": Decimal("0"),
                    "release_reason": "",
                }
            )

        eligible_count = len(candidate_details)
        if eligible_count == 0:
            plan_reason = "no_eligible_market"
            return cls(
                trace_id=trace_id,
                total_budget_usdc=portfolio_budget_usdc,
                allocations=tuple(allocations),
                budget_changes=tuple(budget_changes),
                reason=plan_reason,
            )

        # 等权目标先按可交易、可风控、可吃到盘口深度的 market 数量平均，后续再把释放出来的额度重新分配。
        equal_weight_target_usdc = equal_weight_budget(portfolio_budget_usdc, eligible_count)
        remaining_pool_usdc = portfolio_budget_usdc
        if available_usdc < remaining_pool_usdc:
            remaining_pool_usdc = available_usdc
        remaining_total_capacity_usdc = max_total_usdc - total_exposure_usdc
        if remaining_total_capacity_usdc < remaining_pool_usdc:
            remaining_pool_usdc = remaining_total_capacity_usdc
        if remaining_pool_usdc < Decimal("0"):
            remaining_pool_usdc = Decimal("0")

        active_candidates = [
            candidate
            for candidate in candidate_details
            if candidate["hard_capacity_usdc"] >= candidate["market_min_order_size"]
        ]
        skipped_for_min_order = [
            candidate for candidate in candidate_details if candidate not in active_candidates
        ]
        for candidate in skipped_for_min_order:
            candidate["release_reason"] = candidate["release_reason"] or "below_min_order_size"
        if not active_candidates:
            plan_reason = "no_market_meets_min_order_size"
        elif remaining_pool_usdc < min(
            (candidate["market_min_order_size"] for candidate in active_candidates),
            default=Decimal("0"),
        ):
            for candidate in active_candidates:
                candidate["release_reason"] = candidate["release_reason"] or "below_min_order_size"
            plan_reason = "total_budget_insufficient"
        else:
            while active_candidates and remaining_pool_usdc > Decimal("0"):
                per_market_target_usdc = equal_weight_budget(
                    remaining_pool_usdc,
                    len(active_candidates),
                )
                if per_market_target_usdc <= Decimal("0"):
                    for candidate in active_candidates:
                        candidate["release_reason"] = (
                            candidate["release_reason"] or "below_min_order_size"
                        )
                    plan_reason = "total_budget_insufficient"
                    break

                next_active_candidates: list[dict[str, object]] = []
                allocated_this_round_usdc = Decimal("0")
                for candidate in active_candidates:
                    market_min_order_size = candidate["market_min_order_size"]
                    hard_capacity_usdc = candidate["hard_capacity_usdc"]
                    previous_buy_budget_usdc = candidate["buy_budget_usdc"]
                    available_capacity_usdc = hard_capacity_usdc - previous_buy_budget_usdc

                    if available_capacity_usdc < market_min_order_size:
                        candidate["release_reason"] = (
                            candidate["release_reason"] or "market_limit_reached"
                        )
                        continue

                    buy_budget_usdc = per_market_target_usdc
                    release_reason = ""
                    if buy_budget_usdc > available_capacity_usdc:
                        buy_budget_usdc = available_capacity_usdc
                        release_reason = _capacity_release_reason(
                            available_capacity_usdc=available_capacity_usdc,
                            hard_capacity_usdc=hard_capacity_usdc,
                            depth_usdc=candidate["depth_usdc"],
                        )

                    if buy_budget_usdc < market_min_order_size:
                        next_active_candidates.append(candidate)
                        continue

                    candidate["buy_budget_usdc"] = previous_buy_budget_usdc + buy_budget_usdc
                    candidate["target_budget_usdc"] = equal_weight_target_usdc
                    allocated_this_round_usdc += buy_budget_usdc
                    if buy_budget_usdc < per_market_target_usdc:
                        candidate["release_reason"] = (
                            candidate["release_reason"] or release_reason or "reallocated"
                        )

                    remaining_capacity_after_buy_usdc = (
                        hard_capacity_usdc - candidate["buy_budget_usdc"]
                    )
                    if remaining_capacity_after_buy_usdc >= market_min_order_size:
                        next_active_candidates.append(candidate)

                if allocated_this_round_usdc <= Decimal("0"):
                    for candidate in active_candidates:
                        candidate["release_reason"] = (
                            candidate["release_reason"] or "below_min_order_size"
                        )
                    plan_reason = "budget_remaining_below_min_order_size"
                    break

                remaining_pool_usdc -= allocated_this_round_usdc
                if remaining_pool_usdc < Decimal("0"):
                    remaining_pool_usdc = Decimal("0")
                active_candidates = next_active_candidates

                if active_candidates and equal_weight_budget(
                    remaining_pool_usdc,
                    len(active_candidates),
                ) < min(
                    (candidate["market_min_order_size"] for candidate in active_candidates),
                    default=Decimal("0"),
                ):
                    plan_reason = "budget_remaining_below_min_order_size"
                    break

        allocations.extend(
            _finalize_candidate_allocations(
                candidate_details,
                equal_weight_target_usdc=equal_weight_target_usdc,
            )
        )

        for candidate in candidate_details:
            snapshot = candidate["snapshot"]
            buy_budget_usdc = candidate["buy_budget_usdc"]
            target_budget_usdc = candidate["target_budget_usdc"] or equal_weight_target_usdc
            released_budget_usdc = target_budget_usdc - buy_budget_usdc
            if released_budget_usdc < Decimal("0"):
                released_budget_usdc = Decimal("0")

            release_reason = str(candidate["release_reason"] or "")
            if buy_budget_usdc != target_budget_usdc or release_reason:
                budget_changes.append(
                    MarketBuyBudgetChanged(
                        condition_id=snapshot.condition_id,
                        market_slug=snapshot.market_slug,
                        token_id=snapshot.token_id,
                        previous_buy_budget_usdc=target_budget_usdc,
                        new_buy_budget_usdc=buy_budget_usdc,
                        released_budget_usdc=released_budget_usdc,
                        release_reason=release_reason,
                        current_exposure_usdc=candidate["exposure_usdc"],
                        target_budget_usdc=target_budget_usdc,
                        idempotency_key=snapshot.idempotency_key,
                    )
                )

        return cls(
            trace_id=trace_id,
            total_budget_usdc=portfolio_budget_usdc,
            allocations=tuple(allocations),
            budget_changes=tuple(budget_changes),
            reason=plan_reason,
        )


def equal_weight_budget(portfolio_budget_usdc: Decimal, eligible_market_count: int) -> Decimal:
    if eligible_market_count <= 0:
        return Decimal("0")
    return portfolio_budget_usdc / Decimal(eligible_market_count)


def current_exposure_usdc(position: Position | None, open_orders: Iterable[Order] = ()) -> Decimal:
    exposure_usdc = Decimal("0")
    if position is not None:
        exposure_usdc += position.cost_usdc

        # open SELL 代表已有底层持仓被挂单卖出，仍然占用原始持仓成本；按持仓成本比例近似计入 exposure。
        if position.shares > Decimal("0") and position.open_sell_shares > Decimal("0"):
            open_sell_shares = position.open_sell_shares
            if open_sell_shares > position.shares:
                open_sell_shares = position.shares
            exposure_usdc += position.cost_usdc * (open_sell_shares / position.shares)

    for order in open_orders:
        if order.side != OrderSide.BUY:
            continue
        if order.order_type == OrderType.FAK:
            # FAK pending BUY 可能马上就会被吃掉或撤掉，热路径里按近似 0 处理，避免把短暂挂单放大成持仓。
            continue
        if order.amount_usdc is not None:
            exposure_usdc += order.amount_usdc
            continue
        if order.notional_usdc is not None:
            exposure_usdc += order.notional_usdc
            continue
        if order.price is not None and order.size_shares is not None:
            exposure_usdc += order.price * order.size_shares
    return exposure_usdc


def _allocation_skip_reason(
    snapshot: AllocationMarketSnapshot,
    *,
    entry_no_price_max: Decimal,
    min_liquidity_usdc: Decimal,
    max_spread: Decimal | None,
) -> str:
    if not snapshot.classification_passed:
        return snapshot.classification_reason or "not_crypto_fdv_500m"
    if not snapshot.tradable:
        return "market_not_tradable"
    if not snapshot.market_active:
        return "market_not_active"
    if not snapshot.market_open:
        return "market_not_open"
    if not snapshot.clob_enabled:
        return "clob_disabled"
    if snapshot.resolved:
        return "market_resolved"
    if snapshot.cancelled:
        return "market_cancelled"
    if snapshot.archived:
        return "market_archived"
    if not snapshot.risk_allowed:
        return "risk_limit_reached"

    best_ask = _best_ask(snapshot)
    if best_ask is None:
        return "missing_best_ask"
    if best_ask > entry_no_price_max:
        return "price_above_entry_max"

    liquidity_usdc = _market_liquidity_usdc(snapshot, entry_no_price_max=entry_no_price_max)
    if liquidity_usdc < min_liquidity_usdc:
        return "liquidity_below_min"

    spread = _market_spread(snapshot)
    if max_spread is not None and spread is not None and spread > max_spread:
        return "spread_above_max"

    return ""


def _market_hard_capacity_usdc(
    snapshot: AllocationMarketSnapshot,
    *,
    exposure_usdc: Decimal,
    available_usdc: Decimal,
    max_order_usdc: Decimal,
    max_market_usdc: Decimal,
    entry_no_price_max: Decimal,
    min_liquidity_usdc: Decimal,
    max_spread: Decimal | None,
    liquidity_usdc: Decimal,
    depth_usdc: Decimal,
) -> Decimal:
    best_ask = _best_ask(snapshot)
    if best_ask is None or best_ask > entry_no_price_max:
        return Decimal("0")

    remaining_market_usdc = max_market_usdc - exposure_usdc
    if remaining_market_usdc < Decimal("0"):
        remaining_market_usdc = Decimal("0")

    hard_capacity_usdc = remaining_market_usdc
    if max_order_usdc < hard_capacity_usdc:
        hard_capacity_usdc = max_order_usdc
    if available_usdc < hard_capacity_usdc:
        hard_capacity_usdc = available_usdc
    if liquidity_usdc < min_liquidity_usdc:
        return Decimal("0")
    spread = _market_spread(snapshot)
    if max_spread is not None and spread is not None and spread > max_spread:
        return Decimal("0")
    if depth_usdc < hard_capacity_usdc:
        hard_capacity_usdc = depth_usdc
    if hard_capacity_usdc < Decimal("0"):
        return Decimal("0")
    return hard_capacity_usdc


def _market_liquidity_usdc(
    snapshot: AllocationMarketSnapshot,
    *,
    entry_no_price_max: Decimal,
) -> Decimal:
    if snapshot.liquidity_usdc is not None:
        return snapshot.liquidity_usdc
    return _ask_depth_notional(snapshot.orderbook, entry_no_price_max=entry_no_price_max)


def _market_spread(snapshot: AllocationMarketSnapshot) -> Decimal | None:
    if snapshot.spread is not None:
        return snapshot.spread
    if snapshot.orderbook is not None:
        return snapshot.orderbook.spread
    return None


def _best_ask(snapshot: AllocationMarketSnapshot) -> Decimal | None:
    if snapshot.best_ask is not None:
        return snapshot.best_ask
    if snapshot.orderbook is not None:
        return snapshot.orderbook.best_ask
    return None


def _ask_depth_notional(
    orderbook: OrderbookSnapshot | None,
    *,
    entry_no_price_max: Decimal,
) -> Decimal:
    if orderbook is None:
        return Decimal("0")
    depth_usdc = Decimal("0")
    levels = orderbook.asks
    if not levels and orderbook.best_ask is not None and orderbook.best_ask_size is not None:
        if orderbook.best_ask <= entry_no_price_max:
            return orderbook.best_ask * orderbook.best_ask_size
        return Decimal("0")
    for level in levels:
        if level.price <= entry_no_price_max:
            depth_usdc += level.price * level.size
    return depth_usdc


def _capacity_release_reason(
    *,
    available_capacity_usdc: Decimal,
    hard_capacity_usdc: Decimal,
    depth_usdc: Decimal,
) -> str:
    if available_capacity_usdc <= Decimal("0"):
        return "market_limit_reached"
    if depth_usdc < hard_capacity_usdc:
        return "depth_insufficient"
    return "single_market_limit_reached"


def _finalize_candidate_allocations(
    candidate_details: Iterable[dict[str, object]],
    *,
    equal_weight_target_usdc: Decimal,
) -> list[Allocation]:
    finalized: list[Allocation] = []
    for candidate in candidate_details:
        snapshot = candidate["snapshot"]
        buy_budget_usdc = candidate["buy_budget_usdc"]
        target_budget_usdc = candidate["target_budget_usdc"] or equal_weight_target_usdc
        released_budget_usdc = target_budget_usdc - buy_budget_usdc
        if released_budget_usdc < Decimal("0"):
            released_budget_usdc = Decimal("0")
        finalized.append(
            Allocation(
                condition_id=snapshot.condition_id,
                target_budget_usdc=target_budget_usdc,
                buy_budget_usdc=buy_budget_usdc,
                market_slug=snapshot.market_slug,
                token_id=snapshot.token_id,
                current_exposure_usdc=candidate["exposure_usdc"],
                released_budget_usdc=released_budget_usdc,
                reason=str(candidate["release_reason"] or ""),
                idempotency_key=snapshot.idempotency_key,
                release_reason=str(candidate["release_reason"] or ""),
            )
        )
    return finalized
