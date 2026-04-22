from __future__ import annotations

from polymarket_trader.extension_api import FrameworkCommandAction


def test_extension_commands_only_publish_actions_with_executor_support() -> None:
    assert {action.value for action in FrameworkCommandAction} == {
        "pause_market",
        "resume_market",
        "trigger_reconcile",
    }
