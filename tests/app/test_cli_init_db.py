from __future__ import annotations

import json

from fdv_trader.cli import main as cli_main


class _Settings:
    database_url = "postgresql+asyncpg://fdv:fdv@localhost:5432/fdv"
    masked_database_url = "postgresql+asyncpg://fdv:***@localhost:5432/fdv"


def test_cli_init_db_reads_sys_argv(monkeypatch, capsys) -> None:
    calls: list[str] = []

    async def fake_initialize_database(database_url: str) -> None:
        calls.append(database_url)

    monkeypatch.setattr(cli_main, "load_settings", lambda: _Settings())
    monkeypatch.setattr(cli_main, "initialize_database", fake_initialize_database)
    monkeypatch.setattr(cli_main.sys, "argv", ["fdv-trader", "init-db"])

    cli_main.main()

    payload = json.loads(capsys.readouterr().out)
    assert calls == [_Settings.database_url]
    assert payload == {
        "status": "ok",
        "action": "init-db",
        "database_url": _Settings.masked_database_url,
    }
