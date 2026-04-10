from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("")
async def list_orders() -> dict[str, list[dict[str, str]]]:
    return {"orders": []}

