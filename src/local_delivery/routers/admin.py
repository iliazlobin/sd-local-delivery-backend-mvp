"""Admin router — POST /v1/admin/sweep-reservations."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.db import get_db
from local_delivery.schemas.order import SweepResponse
from local_delivery.services.inventory_service import InventoryService

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/sweep-reservations", response_model=SweepResponse)
async def sweep_reservations(db: AsyncSession = Depends(get_db)) -> SweepResponse:
    """Expire orders in confirmed status > 15 min, release reservations."""
    service = InventoryService(db)
    cancelled = await service.sweep()
    return SweepResponse(
        orders_cancelled=cancelled,
        message=f"Cancelled {cancelled} expired order(s)",
    )
