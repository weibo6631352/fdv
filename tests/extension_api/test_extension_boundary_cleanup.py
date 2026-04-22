from __future__ import annotations

from pathlib import Path

import polymarket_trader.extension_api as extension_api
from polymarket_trader.extension_api import FrameworkCommandAction


def test_extension_api_does_not_export_old_strategy_contract_names() -> None:
    public_names = set(extension_api.__all__)

    assert "ExtensionPorts" in public_names
    assert "ExtensionContext" in public_names
    assert "ExtensionDecision" in public_names
    assert "ExtensionAction" in public_names
    assert all(not name.startswith("Strategy") for name in public_names)


def test_framework_no_longer_uses_removed_host_package() -> None:
    old = "strategy" "_host"
    assert not Path(f"src/polymarket_trader/app/{old}").exists()
    assert not Path(f"tests/app/{old}").exists()


def test_extension_commands_only_publish_actions_with_executor_support() -> None:
    assert {action.value for action in FrameworkCommandAction} == {
        "pause_market",
        "resume_market",
        "trigger_reconcile",
    }
