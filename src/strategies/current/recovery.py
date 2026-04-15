"""当前策略的恢复与修复语义。

这个文件负责回答一个问题：
当账户状态、挂单状态和市场状态不一致时，策略希望框架怎么修。
"""

from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.market import TradingStatus
from polymarket_trader.domain.order import OrderSide
from strategy_sdk import RecoveryDecision, StrategyContext


def decide_recovery(context: StrategyContext) -> RecoveryDecision:
    """根据当前热状态生成恢复计划。

    参数：
        context:
            当前 market 的策略上下文。这里主要使用：
            - ``market``：当前市场状态
            - ``account_snapshot``：账户热状态
            - ``position``：当前持仓
            - ``open_orders``：当前挂单

    返回：
        一个 ``RecoveryDecision``，描述需要取消哪些 BUY、目标 SELL 数量、
        以及是否应该暂停该 market 的进一步交易。

    当前默认规则：
        - 所有仍然 open 的 BUY 都应被取消；
        - 持仓应当由 SELL 覆盖；
        - market 已暂停/关闭/已结算时，恢复流程也应要求暂停交易。
    """

    if context.market is None:
        return RecoveryDecision(reason="missing_market_state")

    account_snapshot = context.account_snapshot
    position = context.position
    if position is None and account_snapshot is not None:
        position = account_snapshot.get_position(
            context.market.condition_id,
            context.market.no_token_id,
        )

    open_orders = context.open_orders
    if not open_orders and account_snapshot is not None:
        open_orders = account_snapshot.open_orders_for_market(
            context.market.condition_id,
            context.market.no_token_id,
        )

    cancel_order_ids = tuple(
        order_id
        for order in open_orders
        for order_id in (_order_identifier(order),)
        if order_id is not None and _is_open_buy(order)
    )
    pause_market = context.market.trading_status in {
        TradingStatus.PAUSED,
        TradingStatus.CLOSED,
        TradingStatus.RESOLVED,
    } or (
        account_snapshot is not None and account_snapshot.is_market_paused(context.market.condition_id)
    )
    return RecoveryDecision(
        reason="strategy_recovery",
        target_sell_size_shares=position.shares if position is not None else Decimal("0"),
        cancel_order_ids=cancel_order_ids,
        pause_market=pause_market,
        pause_reason="market_not_tradable" if pause_market else "",
    )


def _order_identifier(order) -> str | None:
    """提取订单在恢复流程里的稳定标识。"""

    return order.order_id or order.idempotency_key


def _is_open_buy(order) -> bool:
    """判断订单是否是仍需处理的 open BUY。"""

    return order.side == OrderSide.BUY and order.open
