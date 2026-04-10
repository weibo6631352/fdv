from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    polymarket_clob_host: str = "https://clob.polymarket.com"
    polymarket_gamma_host: str = "https://gamma-api.polymarket.com"
    polymarket_data_host: str = "https://data-api.polymarket.com"
    polymarket_market_ws: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    polymarket_user_ws: str = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    portfolio_budget_usdc: Decimal = Decimal("0")
    max_order_usdc: Decimal = Decimal("0")
    max_market_usdc: Decimal = Decimal("0")
    max_total_usdc: Decimal = Decimal("0")
    entry_no_price_max: Decimal = Decimal("0.60")
    exit_no_price: Decimal = Decimal("0.70")
    min_liquidity_usdc: Decimal = Decimal("0")
    max_spread: Decimal = Decimal("0")
    market_sync_interval_seconds: int = 60
    order_retry_limit: int = 2
    max_open_orders: int = 50

    enable_uvloop: bool = True
    trading_event_queue_max_size: int = 1000
    maintenance_event_queue_max_size: int = 1000
    persistence_event_queue_max_size: int = 5000
    trading_worker_threads: int = 4
    maintenance_worker_threads: int = 4
    maintenance_process_workers: int = 2
    order_submit_timeout_ms: int = 3000
    order_sign_timeout_ms: int = 1000
    critical_lock_timeout_ms: int = 20
    trading_queue_warn_depth: int = 100
    entry_signal_to_submit_warn_ms: int = 500

    database_url: str = "postgresql+asyncpg://fdv:fdv@localhost:5432/fdv"


def load_settings() -> Settings:
    return Settings()

