from __future__ import annotations

from pathlib import Path

from polymarket_trader.app.strategy_host import run_entry_replay


def test_run_entry_replay_uses_explicit_extension_fixture() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "strategies"
        / "fixtures"
        / "entry_replay.json"
    )

    payload = run_entry_replay(
        str(fixture_path),
        extension_module="tests.helpers.demo_extension",
    )

    assert payload["extension"]["name"] == "demo"
    assert payload["extension"]["extension_module"] == "tests.helpers.demo_extension"
    assert payload["plan"]["ready_to_trade"] is True
    assert payload["plan"]["intent"]["amount_usdc"] == "50"


def test_run_entry_replay_requires_extension_module() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "strategies"
        / "fixtures"
        / "entry_replay.json"
    )

    try:
        run_entry_replay(str(fixture_path))
    except ValueError as exc:
        assert str(exc) == "extension_module is required for entry replay"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("expected ValueError")
