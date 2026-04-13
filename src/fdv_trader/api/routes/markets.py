from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal

from fdv_trader.api.deps import get_admin_service
from fdv_trader.app.admin_service import AdminService

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("/detail")
async def get_market_detail(
    market_slug: str | None = Query(default=None),
    condition_id: str | None = Query(default=None),
    token_id: str | None = Query(default=None),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    if not any((market_slug, condition_id, token_id)):
        raise HTTPException(status_code=422, detail="market_slug, condition_id, or token_id is required")
    payload = await service.get_market(
        market_slug=market_slug,
        condition_id=condition_id,
        token_id=token_id,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="market not found")
    return payload


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
