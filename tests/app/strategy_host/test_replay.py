from __future__ import annotations

from pathlib import Path

from polymarket_trader.app.strategy_host import run_entry_replay


def test_run_entry_replay_uses_current_strategy_fixture() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "strategies"
        / "fixtures"
        / "entry_replay.json"
    )

    payload = run_entry_replay(str(fixture_path))

    assert payload["strategy"]["name"] == "current"
    assert payload["strategy"]["module_path"] == "strategies.current"
    assert payload["plan"]["ready_to_trade"] is True
    assert payload["plan"]["intent"]["amount_usdc"] == "50"
