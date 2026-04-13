from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from fdv_trader.api.deps import get_admin_service
from fdv_trader.app.admin_service import AdminService
from fdv_trader.infra.polymarket import PolymarketClientError

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/detail")
async def get_profile_detail(
    address: str = Query(pattern=r"^0x[a-fA-F0-9]{40}$"),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    try:
        return await service.get_profile(address=address)
    except PolymarketClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="profile not found") from exc
        raise HTTPException(status_code=502, detail="profile_upstream_unavailable") from exc
    except RuntimeError as exc:
        if str(exc) != "gamma_client unavailable":
            raise
        raise HTTPException(status_code=503, detail="gamma_client_unavailable") from exc


@router.get("/activity")
async def get_profile_activity(
    address: str = Query(pattern=r"^0x[a-fA-F0-9]{40}$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=10000),
    condition_id: str | None = Query(default=None, pattern=r"^0x[a-fA-F0-9]{64}$"),
    event_id: int | None = Query(default=None, ge=1),
    type_: Literal[
        "TRADE",
        "SPLIT",
        "MERGE",
        "REDEEM",
        "REWARD",
        "CONVERSION",
        "MAKER_REBATE",
        "REFERRAL_REWARD",
    ]
    | None = Query(default=None, alias="type"),
    start: int | None = Query(default=None, ge=0),
    end: int | None = Query(default=None, ge=0),
    sort_by: Literal["TIMESTAMP", "TOKENS", "CASH"] | None = Query(default=None),
    sort_direction: Literal["ASC", "DESC"] | None = Query(default=None),
    side: Literal["BUY", "SELL"] | None = Query(default=None),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    if condition_id is not None and event_id is not None:
        raise HTTPException(status_code=422, detail="condition_id and event_id are mutually exclusive")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start must be <= end")
    try:
        return await service.list_profile_activity(
            address=address,
            limit=limit,
            offset=offset,
            condition_id=condition_id,
            event_id=event_id,
            activity_type=type_,
            start=start,
            end=end,
            sort_by=sort_by,
            sort_direction=sort_direction,
            side=side,
        )
    except PolymarketClientError as exc:
        raise HTTPException(status_code=502, detail="profile_activity_upstream_unavailable") from exc
    except RuntimeError as exc:
        if str(exc) != "data_client unavailable":
            raise
        raise HTTPException(status_code=503, detail="data_client_unavailable") from exc


@router.get("/search")
async def search_profiles(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    try:
        return await service.search_profiles(
            query=q,
            limit=limit,
            page=page,
        )
    except PolymarketClientError as exc:
        raise HTTPException(status_code=502, detail="profile_search_upstream_unavailable") from exc
    except RuntimeError as exc:
        if str(exc) != "gamma_client unavailable":
            raise
        raise HTTPException(status_code=503, detail="gamma_client_unavailable") from exc
