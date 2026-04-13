from __future__ import annotations

from polymarket_trader.domain.market import Market, TradingStatus
from polymarket_trader.runtime.account_state import AccountSnapshot

from polymarket_trader.strategies.current.config import CurrentStrategyConfig


def should_keep_tracking(
    market: Market,
    account_snapshot: AccountSnapshot | None,
    config: CurrentStrategyConfig,
) -> bool:
    """决定 market 被策略排除后，是否继续保留订阅/跟踪。

    当前规则很直接：
    - 只要还有持仓、挂单，继续保留跟踪；
    - 等 exposure 归零后，再让框架移除 registry / WS 订阅。
    """

    if not config.retain_filtered_market_tracking:
        return False
    if account_snapshot is None:
        return True

    position = account_snapshot.get_position(market.condition_id, market.no_token_id)
    if position is not None and (
        position.shares > 0
        or position.open_buy_shares > 0
        or position.open_sell_shares > 0
        or position.pending_buy_shares > 0
    ):
        return True
    return bool(account_snapshot.open_orders_for_market(market.condition_id, market.no_token_id))


def build_filtered_tracking_market(
    candidate_market: Market,
    *,
    existing_market: Market,
    reason: str,
) -> Market:
    """为“已排除但继续保留跟踪”的 market 生成运行时状态。"""

    if existing_market.trading_status in {
        TradingStatus.CLOSED,
        TradingStatus.RESOLVED,
        TradingStatus.REJECTED,
    }:
        return candidate_market.with_trading_status(
            existing_market.trading_status,
            reject_reason=existing_market.reject_reason,
        )
    return candidate_market.with_trading_status(
        TradingStatus.PAUSED,
        reject_reason=reason or "strategy_filtered_out",
    )
