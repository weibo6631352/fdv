from __future__ import annotations

from polymarket_trader.app.extension_commands import ExtensionCommandExecutor
from polymarket_trader.extension_api import ExtensionCommand, FrameworkCommandAction
from polymarket_trader.runtime.account_state import AccountStateStore


def test_pause_market_command_updates_runtime_state() -> None:
    account_state = AccountStateStore()
    executor = ExtensionCommandExecutor(account_state_store=account_state)

    result = executor.execute(
        ExtensionCommand.pause_market(condition_id="condition", reason="business_pause"),
        trace_id="trace",
    )

    snapshot = account_state.snapshot()
    assert result.accepted
    assert result.action is FrameworkCommandAction.PAUSE_MARKET
    assert snapshot.is_market_paused("condition")


def test_pause_market_command_missing_condition_id_is_rejected() -> None:
    account_state = AccountStateStore()
    executor = ExtensionCommandExecutor(account_state_store=account_state)

    result = executor.execute(
        ExtensionCommand(
            action=FrameworkCommandAction.PAUSE_MARKET,
            reason="business_pause",
        ),
        trace_id="trace",
    )

    assert not result.accepted
    assert result.action is FrameworkCommandAction.PAUSE_MARKET
    assert result.reason == "missing_condition_id"


def test_pause_market_command_without_account_state_store_is_rejected() -> None:
    executor = ExtensionCommandExecutor()

    result = executor.execute(
        ExtensionCommand.pause_market(condition_id="condition", reason="business_pause"),
        trace_id="trace",
    )

    assert not result.accepted
    assert result.action is FrameworkCommandAction.PAUSE_MARKET
    assert result.reason == "missing_account_state_store"


def test_resume_market_command_without_account_state_store_is_rejected() -> None:
    executor = ExtensionCommandExecutor()

    result = executor.execute(
        ExtensionCommand(
            action=FrameworkCommandAction.RESUME_MARKET,
            condition_id="condition",
            reason="business_resume",
        ),
        trace_id="trace",
    )

    assert not result.accepted
    assert result.action is FrameworkCommandAction.RESUME_MARKET
    assert result.reason == "missing_account_state_store"


def test_unsupported_extension_command_is_rejected() -> None:
    executor = ExtensionCommandExecutor()

    result = executor.execute(
        ExtensionCommand(
            action=FrameworkCommandAction.REFRESH_MARKET,
            condition_id="condition",
            reason="manual_refresh",
        ),
        trace_id="trace",
    )

    assert not result.accepted
    assert result.action is FrameworkCommandAction.REFRESH_MARKET
    assert result.reason == "unsupported_command"


def test_trigger_reconcile_command_is_recorded_without_direct_side_effect() -> None:
    executor = ExtensionCommandExecutor()
    result = executor.execute(
        ExtensionCommand.trigger_reconcile(condition_id="condition", reason="manual_recheck"),
        trace_id="trace",
    )

    assert result.accepted
    assert result.action is FrameworkCommandAction.TRIGGER_RECONCILE
    assert result.command.reason == "manual_recheck"
