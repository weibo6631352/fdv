from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator

from fdv_trader.api.deps import get_admin_service
from fdv_trader.app.admin_service import AdminService

router = APIRouter(prefix="/orders", tags=["orders"])


class CancelReplaceSellRequest(BaseModel):
    market_slug: str | None = None
    condition_id: str | None = None
    token_id: str | None = None
    new_price: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    operator: str = "manual"
    reason: str = "admin_cancel_replace_sell"
    trace_id: str | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> "CancelReplaceSellRequest":
        if not any((self.market_slug, self.condition_id, self.token_id)):
            raise ValueError("market_slug, condition_id, or token_id is required")
        return self


@router.get("")
async def list_orders(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    open_only: bool = Query(default=True),
    condition_id: str | None = Query(default=None),
    token_id: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    return await service.list_orders(
        limit=limit,
        offset=offset,
        open_only=open_only,
        condition_id=condition_id,
        token_id=token_id,
        trace_id=trace_id,
    )


@router.post("/cancel-replace-sell")
async def cancel_replace_sell(
    request: CancelReplaceSellRequest,
    service: AdminService = Depends(get_admin_service),
) -> dict[str, object]:
    return await service.cancel_replace_sell(
        market_slug=request.market_slug,
        condition_id=request.condition_id,
        token_id=request.token_id,
        new_price=request.new_price,
        operator=request.operator,
        reason=request.reason,
        trace_id=request.trace_id,
    )
