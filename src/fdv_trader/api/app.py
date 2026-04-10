from __future__ import annotations

from fastapi import FastAPI

from fdv_trader.api.routes import health, markets, orders, portfolio


def create_app() -> FastAPI:
    app = FastAPI(title="FDV Trader Admin API")
    app.include_router(health.router)
    app.include_router(markets.router)
    app.include_router(orders.router)
    app.include_router(portfolio.router)
    return app

