from __future__ import annotations

from decimal import Decimal

from polymarket_trader.domain.market import Market
from polymarket_trader.runtime.account_state import AccountSnapshot
from polymarket_trader.strategy_api.models import (
    DiscoveryQuery,
    EntrySizing,
    RecoveryDecision,
    StrategySpec,
    StrategyContext,
    StrategyDecision,
    UniverseDecision,
)
from polymarket_trader.strategies.current.config import (
    ENTRY_NO_PRICE_MAX,
    EXIT_NO_PRICE,
    MAX_SPREAD,
    MIN_LIQUIDITY_USDC,
)
from polymarket_trader.strategies.current.market_filter import (
    build_discovery_queries,
    select_market,
)
from polymarket_trader.strategies.current.subscription import (
    build_filtered_tracking_market,
    should_keep_tracking,
)
from polymarket_trader.strategies.current.trading_strategy import (
    decide_entry,
    decide_exit,
    decide_recovery,
    size_entry,
)


class CurrentStrategy:
    """当前运行时固定装配的策略入口。

    二次开发时优先阅读：
    - `config.py`：交易阈值常量
    - `market_filter.py`：市场筛选与 discovery
    - `trading_strategy.py`：分配、入场、退出、恢复
    - `subscription.py`：订阅保留与退订规则
    """

    def __init__(self) -> None:
        self._spec = StrategySpec(
            name="current",
            version="1",
            description="Current runtime strategy implementation",
            capabilities=("discovery", "universe", "sizing", "entry", "exit", "recovery"),
        )

    @property
    def spec(self) -> StrategySpec:
        return self._spec

    @property
    def entry_no_price_max(self) -> Decimal:
        return ENTRY_NO_PRICE_MAX

    @property
    def exit_no_price(self) -> Decimal:
        return EXIT_NO_PRICE

    @property
    def min_liquidity_usdc(self) -> Decimal:
        return MIN_LIQUIDITY_USDC

    @property
    def max_spread(self) -> Decimal | None:
        return MAX_SPREAD

    def build_discovery_queries(self) -> tuple[DiscoveryQuery, ...]:
        return build_discovery_queries()

    def select_market(self, market: Market) -> UniverseDecision:
        return select_market(market)

    def size_entry(self, context: StrategyContext) -> EntrySizing:
        return size_entry(context)

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        return decide_entry(context)

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        return decide_exit(context)

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        return decide_recovery(context)

    def should_keep_tracking(
        self,
        market: Market,
        account_snapshot: AccountSnapshot | None,
    ) -> bool:
        return should_keep_tracking(market, account_snapshot)

    def build_filtered_tracking_market(
        self,
        candidate_market: Market,
        *,
        existing_market: Market,
        reason: str,
    ) -> Market:
        return build_filtered_tracking_market(
            candidate_market,
            existing_market=existing_market,
            reason=reason,
        )


def build_strategy() -> CurrentStrategy:
    """构造当前运行时策略。

    这里不再读取外部策略配置文件。
    交易阈值写在 `config.py` 常量里，市场筛选语义写在 `market_filter.py`。
    """

    return CurrentStrategy()
