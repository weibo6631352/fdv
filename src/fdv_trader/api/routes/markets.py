from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("")
async def list_markets() -> dict[str, list[dict[str, str]]]:
    return {"markets": []}

