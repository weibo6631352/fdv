"""Database infrastructure."""

from fdv_trader.infra.db.models import (
    AllocationModel,
    AuditEventModel,
    Base,
    FillModel,
    MarketModel,
    OrderModel,
    OrderbookSnapshotModel,
    OutboxEventModel,
    PositionModel,
)
from fdv_trader.infra.db.persistence import DatabasePersistenceRepository
from fdv_trader.infra.db.repositories import (
    AllocationRepository,
    AuditEventRepository,
    BaseRepository,
    FillRepository,
    MarketRepository,
    OrderRepository,
    OrderbookSnapshotRepository,
    OutboxEventRepository,
    PositionRepository,
    RepositoryPage,
)
from fdv_trader.infra.db.session import build_engine, build_session_factory

__all__ = [
    "AllocationModel",
    "AllocationRepository",
    "AuditEventModel",
    "AuditEventRepository",
    "Base",
    "BaseRepository",
    "DatabasePersistenceRepository",
    "FillModel",
    "FillRepository",
    "MarketModel",
    "MarketRepository",
    "OrderModel",
    "OrderRepository",
    "OrderbookSnapshotModel",
    "OrderbookSnapshotRepository",
    "OutboxEventModel",
    "OutboxEventRepository",
    "PositionModel",
    "PositionRepository",
    "RepositoryPage",
    "build_engine",
    "build_session_factory",
]
