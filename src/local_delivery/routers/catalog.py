"""Catalog browse & search router — GET /v1/catalog."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.db import get_db
from local_delivery.redis import get_redis
from local_delivery.schemas.catalog import CatalogPage
from local_delivery.services.catalog_service import CatalogService

router = APIRouter(prefix="/v1", tags=["catalog"])


@router.get("/catalog", response_model=CatalogPage)
async def browse_catalog(
    dc_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> CatalogPage:
    """Browse or search products at a DC with availability."""
    if not dc_id:
        raise HTTPException(status_code=400, detail="dc_id is required")

    service = CatalogService(db, redis)
    result = await service.browse(
        dc_id=dc_id,
        category=category,
        q=q,
        page=page,
        page_size=page_size,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="DC not found")
    return CatalogPage(**result)
