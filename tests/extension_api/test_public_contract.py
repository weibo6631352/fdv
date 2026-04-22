from __future__ import annotations

from decimal import Decimal

from polymarket_trader.extension_api import (
    AccountSnapshotView,
    DiscoveryEndpoint,
    DiscoveryQuery,
    EntrySizing,
    ExtensionCommand,
    ExtensionHooks,
    ExtensionManifest,
    FrameworkCommandAction,
    StrategyAction,
    StrategyContext,
    StrategyDecision,
    StrategyPorts,
    UniverseDecision,
)


def test_extension_api_exports_core_contracts() -> None:
    query = DiscoveryQuery(endpoint=DiscoveryEndpoint.MARKETS, params={"active": True})
    decision = StrategyDecision.buy(
        reason="entry",
        token_id="token",
        price=Decimal("0.42"),
        amount_usdc=Decimal("5"),
    )
    command = ExtensionCommand.pause_market(condition_id="condition", reason="business_pause")

    assert query.endpoint is DiscoveryEndpoint.MARKETS
    assert decision.action is StrategyAction.BUY
    assert command.action is FrameworkCommandAction.PAUSE_MARKET
    assert ExtensionHooks is not None
    assert ExtensionManifest is not None
    assert StrategyContext is not None
    assert StrategyPorts is not None
    assert AccountSnapshotView is not None
    assert EntrySizing is not None
    assert UniverseDecision.include(reason="ok").selected
