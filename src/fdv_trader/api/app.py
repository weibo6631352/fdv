from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from fdv_trader.app.admin_service import AdminService
from fdv_trader.api.routes import fills, health, markets, operations, orders, portfolio, positions
from fdv_trader.api.routes import runtime as runtime_route
from fdv_trader.main import create_runtime, shutdown_runtime


def create_app(*, runtime: Any | None = None, admin_service: AdminService | None = None) -> FastAPI:
    owns_runtime = runtime is None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bound_runtime = runtime
        if bound_runtime is None:
            bound_runtime = await create_runtime()
        bound_service = admin_service or getattr(bound_runtime, "admin_service", None) or AdminService()
        if getattr(bound_service, "runtime", None) is None:
            bound_service = bound_service.bind_runtime(bound_runtime)
        app.state.runtime = bound_runtime
        app.state.admin_service = bound_service
        app.state.get_runtime = lambda: app.state.runtime
        app.state.get_admin_service = lambda: app.state.admin_service
        if getattr(bound_runtime, "admin_service", None) is None:
            bound_runtime.admin_service = bound_service
        try:
            yield
        finally:
            if owns_runtime:
                await shutdown_runtime(bound_runtime)

    app = FastAPI(title="FDV Trader Admin API", lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(runtime_route.router)
    app.include_router(markets.router)
    app.include_router(orders.router)
    app.include_router(fills.router)
    app.include_router(positions.router)
    app.include_router(portfolio.router)
    app.include_router(operations.router)
    return app
