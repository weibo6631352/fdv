from __future__ import annotations

from decimal import Decimal

from polymarket_trader.extension_api import (
    AccountSnapshotView,
    DiscoveryQuery,
    EntrySizing,
    ExtensionCommand,
    ExtensionHooks,
    ExtensionManifest,
    FrameworkCommandAction,
    ExtensionAction,
    ExtensionContext,
    ExtensionDecision,
    ExtensionPorts,
    UniverseDecision,
)


def test_extension_api_exports_core_contracts() -> None:
    decision = ExtensionDecision.buy(
        reason="entry",
        token_id="token",
        price=Decimal("0.42"),
        amount_usdc=Decimal("5"),
    )
    command = ExtensionCommand.pause_market(condition_id="condition", reason="business_pause")

    assert decision.action is ExtensionAction.BUY
    assert command.action is FrameworkCommandAction.PAUSE_MARKET
    assert ExtensionHooks is not None
    assert ExtensionManifest is not None
    assert ExtensionContext is not None
    assert ExtensionPorts is not None
    assert AccountSnapshotView is not None
    assert DiscoveryQuery(name="fdv", params={"title_search": "fdv"}).params["title_search"] == "fdv"
    assert EntrySizing is not None
    assert UniverseDecision.include(reason="ok").selected
