"""DC lookup router — GET /v1/dc/lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.db import get_db
from local_delivery.schemas.dc import DCLookupResponse
from local_delivery.services.dc_service import DCService

router = APIRouter(prefix="/v1/dc", tags=["dc"])


@router.get("/lookup", response_model=DCLookupResponse)
async def lookup_dc(
    lat: float = Query(...),
    lon: float = Query(...),
    db: AsyncSession = Depends(get_db),
) -> DCLookupResponse:
    """Find the nearest active DC serving a geographic point."""
    service = DCService(db)
    result = await service.find_nearest(lat, lon)
    if result is None:
        raise HTTPException(status_code=404, detail="No DC covers this location")
    return DCLookupResponse(**result)
