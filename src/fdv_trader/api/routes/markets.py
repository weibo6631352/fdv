from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from typing import Literal

from fdv_trader.api.deps import get_admin_service
from fdv_trader.app.admin_service import AdminService

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("")
async def list_markets(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    trading_status: str | None = Query(default=None),
    fees_enabled: bool | None = Query(default=None),
    fee_rate_bps_min: int | None = Query(default=None, ge=0),
    fee_rate_bps_max: int | None = Query(default=None, ge=0),
    maker_base_fee_bps_min: int | None = Query(default=None, ge=0),
    maker_base_fee_bps_max: int | None = Query(default=None, ge=0),
    taker_base_fee_bps_min: int | None = Query(default=None, ge=0),
    taker_base_fee_bps_max: int | None = Query(default=None, ge=0),
    sort_by: Literal[
        "market_slug",
        "fee_rate_bps",
        "fee_rate_updated_at",
        "maker_base_fee_bps",
        "taker_base_fee_bps",
    ]
    | None = Query(default=None),
    sort_direction: Literal["asc", "desc"] = Query(default="desc"),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    return await service.list_markets(
        limit=limit,
        offset=offset,
        trading_status=trading_status,
        fees_enabled=fees_enabled,
        fee_rate_bps_min=fee_rate_bps_min,
        fee_rate_bps_max=fee_rate_bps_max,
        maker_base_fee_bps_min=maker_base_fee_bps_min,
        maker_base_fee_bps_max=maker_base_fee_bps_max,
        taker_base_fee_bps_min=taker_base_fee_bps_min,
        taker_base_fee_bps_max=taker_base_fee_bps_max,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
