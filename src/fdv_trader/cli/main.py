from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
import os
from collections.abc import Sequence
import sys
from typing import Any

import httpx
import uvicorn

from fdv_trader.api.app import create_app
from fdv_trader.config import load_settings
from fdv_trader.infra.db import initialize_database
from fdv_trader.strategy_api.replay import run_entry_replay

DEFAULT_ADMIN_API_URL = (
    os.environ.get("FDV_ADMIN_API_URL")
    or os.environ.get("ADMIN_API_URL")
    or "http://127.0.0.1:8000"
)


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv:
        argv = ["run"]

    parser = argparse.ArgumentParser(prog="fdv-trader")
    parser.add_argument("--base-url", default=DEFAULT_ADMIN_API_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "config-summary", "status", "reconcile", "init-db", "replay"],
    )
    parser.add_argument("--trace-id", dest="trace_id", default=None)
    parser.add_argument("--condition-id", dest="condition_ids", action="append", default=[])
    parser.add_argument("--fixture", default=None)
    parser.add_argument("--strategy-config", dest="strategy_config_path", default=None)
    args = parser.parse_args(argv)

    if args.command == "run":
        _run_server(host=args.host, port=args.port)
        return
    if args.command == "init-db":
        asyncio.run(_initialize_database())
        return
    if args.command == "replay":
        if not args.fixture:
            raise SystemExit("--fixture is required for replay")
        _print_json(
            run_entry_replay(
                args.fixture,
                strategy_config_path=args.strategy_config_path,
            )
        )
        return

    try:
        asyncio.run(_dispatch_admin_command(args))
    except httpx.HTTPError as exc:
        raise SystemExit(str(exc)) from exc


def _run_server(*, host: str, port: int) -> None:
    settings = load_settings()
    if settings.enable_uvloop:
        with suppress(Exception):
            import uvloop

            uvloop.install()
    uvicorn.run(create_app(), host=host, port=port, log_config=None)


async def _dispatch_admin_command(args: argparse.Namespace) -> None:
    async with httpx.AsyncClient(base_url=args.base_url, timeout=args.timeout) as client:
        if args.command == "config-summary":
            payload = await _get_json(client, "/runtime")
            _print_json(payload.get("settings", {}))
            return
        if args.command == "status":
            payload = await _get_json(client, "/runtime")
            _print_json(payload.get("runtime", payload))
            return
        if args.command == "reconcile":
            payload = await _post_json(
                client,
                "/operations/reconcile",
                json_body={
                    "trace_id": args.trace_id,
                    "condition_ids": args.condition_ids,
                },
            )
            _print_json(payload)
            return
        raise SystemExit(f"unsupported command: {args.command}")


async def _initialize_database() -> None:
    settings = load_settings()
    await initialize_database(settings.database_url)
    _print_json(
        {
            "status": "ok",
            "action": "init-db",
            "database_url": settings.masked_database_url,
        }
    )


async def _get_json(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    response = await client.get(path)
    response.raise_for_status()
    return response.json()


async def _post_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    json_body: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(path, json=json_body)
    response.raise_for_status()
    return response.json()


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main(sys.argv[1:])
