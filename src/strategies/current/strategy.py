"""当前默认策略的装配入口。

这个文件把 discovery、universe、trading、recovery、tracking 这些子模块
组装成一个完整的 ``StrategyModule`` 实现。
"""

from __future__ import annotations

from strategy_sdk import (
    AccountSnapshotView,
    DiscoveryQuery,
    EntrySizing,
    RecoveryDecision,
    StrategyContext,
    StrategyDecision,
    StrategyModule,
    StrategyPorts,
    StrategyRuntimeProfile,
    StrategySpec,
    UniverseDecision,
)

from polymarket_trader.domain.market import Market

from strategies.current.config import CurrentStrategyConfig, load_current_strategy_config
from strategies.current.discovery import build_discovery_queries
from strategies.current.recovery import decide_recovery
from strategies.current.tracking import build_filtered_tracking_market, should_keep_tracking
from strategies.current.trading import decide_entry, decide_exit, size_entry
from strategies.current.universe import select_market


class CurrentStrategy:
    """当前默认策略的主对象。

    这个类本身尽量保持“薄”：
    - 配置定义在 ``config.py``
    - 远端扫描定义在 ``discovery.py``
    - 市场筛选定义在 ``universe.py``
    - 分配、入场、退出定义在 ``trading.py``
    - 恢复定义在 ``recovery.py``
    - 过滤后继续跟踪的规则定义在 ``tracking.py``

    这样拆分后，二次开发可以直接按关注点替换单个文件，
    不必在一个大类里来回跳。
    """

    def __init__(
        self,
        *,
        config: CurrentStrategyConfig,
        ports: StrategyPorts | None = None,
    ) -> None:
        """初始化当前策略。

        参数：
            config:
                当前策略配置对象，包含价格阈值、扫描词、筛选 token 等业务参数。
            ports:
                框架注入给策略的应用层端口集合。当前默认策略暂时没有深度使用，
                但这里保留接口，是为了让后续策略能通过稳定端口读取市场、
                账户、运行时和遥测能力，而不是直接依赖框架内部实现。
        """

        self._config = config
        self._ports = ports or StrategyPorts()
        self._spec = StrategySpec(
            name="current",
            version="1",
            description="Current runtime strategy implementation",
            config_type=CurrentStrategyConfig,
            capabilities=(
                "discovery",
                "universe",
                "sizing",
                "entry",
                "exit",
                "recovery",
                "tracking",
            ),
        )
        self._runtime_profile = StrategyRuntimeProfile(
            entry_no_price_max=config.entry_no_price_max,
            min_liquidity_usdc=config.min_liquidity_usdc,
            max_spread=config.max_spread,
        )

    @property
    def spec(self) -> StrategySpec:
        """返回策略元信息。

        框架会用它展示策略名、版本、能力列表以及配置类型。
        """

        return self._spec

    @property
    def runtime_profile(self) -> StrategyRuntimeProfile:
        """返回运行时 profile。

        这些值不是直接做交易决策，而是给框架热路径提供公共阈值，
        比如盘口 watcher 和 risk gate 需要提前知道的价格/深度/spread 门槛。
        """

        return self._runtime_profile

    @property
    def ports(self) -> StrategyPorts:
        """暴露框架注入的应用层端口。

        当前默认策略主要依赖传入的 ``StrategyContext``，
        但其他策略可以在内部按需使用这些端口读取更多运行时信息。
        """

        return self._ports

    def build_discovery_queries(self) -> tuple[DiscoveryQuery, ...]:
        """返回远端 discovery 查询集合。"""

        return build_discovery_queries(self._config)

    def select_market(self, market: Market) -> UniverseDecision:
        """判断 market 是否属于当前策略 universe。"""

        return select_market(self._config, market)

    def size_entry(self, context: StrategyContext) -> EntrySizing:
        """为当前 market 生成入场预算分配结果。"""

        return size_entry(self._config, context)

    def decide_entry(self, context: StrategyContext) -> StrategyDecision:
        """根据盘口和预算生成 BUY 决策。"""

        return decide_entry(self._config, context)

    def decide_exit(self, context: StrategyContext) -> StrategyDecision:
        """根据持仓状态生成 SELL 决策。"""

        return decide_exit(self._config, context)

    def decide_recovery(self, context: StrategyContext) -> RecoveryDecision:
        """根据热状态生成恢复语义。"""

        return decide_recovery(context)

    def should_keep_tracking(
        self,
        market: Market,
        account_snapshot: AccountSnapshotView | None,
    ) -> bool:
        """判断已被过滤 market 是否继续保留跟踪。"""

        return should_keep_tracking(market, account_snapshot)

    def build_filtered_tracking_market(
        self,
        candidate_market: Market,
        *,
        existing_market: Market,
        reason: str,
    ) -> Market:
        """构造“继续跟踪但已被排除”的 market 运行时状态。"""

        return build_filtered_tracking_market(
            candidate_market,
            existing_market=existing_market,
            reason=reason,
        )


def build_strategy(
    *,
    ports: StrategyPorts | None = None,
    config_path: str | None = None,
) -> StrategyModule:
    """构造当前策略实例。

    参数：
        ports:
            框架注入的应用层端口集合。
        config_path:
            可选外部配置文件路径。未提供时使用默认配置。

    返回：
        一个符合 ``StrategyModule`` 协议的当前策略实例。
    """

    return CurrentStrategy(
        config=load_current_strategy_config(config_path),
        ports=ports,
    )
