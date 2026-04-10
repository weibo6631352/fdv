from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from fdv_trader.cli import main as cli_main


@dataclass(frozen=True, slots=True)
class FakeResponse:
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        return None


class FakeAsyncClient:
    instances: list["FakeAsyncClient"] = []

    def __init__(self, *, base_url: str, timeout: float) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        FakeAsyncClient.instances.append(self)

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    async def get(self, path: str) -> FakeResponse:
        self.calls.append(("GET", path, None))
        if path == "/runtime":
            return FakeResponse(
                {
                    "settings": {"portfolio_budget_usdc": "100", "entry_no_price_max": "0.60"},
                    "runtime": {"phase": "trading_enabled", "ready_to_trade": True},
                }
            )
        raise AssertionError(f"unexpected GET path: {path}")

    async def post(self, path: str, json: dict[str, Any]) -> FakeResponse:  # noqa: A002
        self.calls.append(("POST", path, json))
        if path == "/operations/reconcile":
            return FakeResponse(
                {
                    "status": "ok",
                    "trace_id": json["trace_id"],
                    "condition_ids": json["condition_ids"],
                }
            )
        raise AssertionError(f"unexpected POST path: {path}")


def test_cli_config_summary_and_status_commands(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_main.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.instances.clear()

    cli_main.main(["config-summary", "--base-url", "http://admin.local", "--timeout", "3"])
    config_summary_output = json.loads(capsys.readouterr().out)

    cli_main.main(["status", "--base-url", "http://admin.local", "--timeout", "3"])
    status_output = json.loads(capsys.readouterr().out)

    assert config_summary_output == {
        "portfolio_budget_usdc": "100",
        "entry_no_price_max": "0.60",
    }
    assert status_output == {"phase": "trading_enabled", "ready_to_trade": True}
    assert FakeAsyncClient.instances[0].calls == [("GET", "/runtime", None)]
    assert FakeAsyncClient.instances[1].calls == [("GET", "/runtime", None)]


def test_cli_reconcile_command_posts_trace_and_condition_ids(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_main.httpx, "AsyncClient", FakeAsyncClient)
    FakeAsyncClient.instances.clear()

    cli_main.main(
        [
            "reconcile",
            "--base-url",
            "http://admin.local",
            "--timeout",
            "3",
            "--trace-id",
            "trace-cli",
            "--condition-id",
            "condition-1",
            "--condition-id",
            "condition-2",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "status": "ok",
        "trace_id": "trace-cli",
        "condition_ids": ["condition-1", "condition-2"],
    }
    assert FakeAsyncClient.instances[0].calls == [
        (
            "POST",
            "/operations/reconcile",
            {"trace_id": "trace-cli", "condition_ids": ["condition-1", "condition-2"]},
        )
    ]
