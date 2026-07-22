"""Order router — POST /v1/orders, GET/POST /v1/orders/{id}."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.db import get_db
from local_delivery.services.order_service import OrderService

router = APIRouter(prefix="/v1/orders", tags=["orders"])


@router.post("")
async def create_order(request: Request, db: AsyncSession = Depends(get_db)):
    """Create an order with atomic inventory reservation."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    dc_id = body.get("dc_id")
    if not dc_id:
        raise HTTPException(status_code=400, detail="dc_id is required")

    items = body.get("items")
    if not items or not isinstance(items, list) or len(items) == 0:
        raise HTTPException(status_code=400, detail="items is required")

    delivery_address = body.get("delivery_address")
    if not delivery_address:
        raise HTTPException(status_code=400, detail="delivery_address is required")

    order_id_raw = body.get("order_id")
    if not order_id_raw:
        raise HTTPException(status_code=400, detail="order_id is required")

    try:
        order_id = UUID(order_id_raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid order_id format") from None

    # Parse items
    parsed_items = []
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Invalid item format")
        pid_raw = item.get("product_id")
        qty = item.get("quantity")
        if not pid_raw:
            raise HTTPException(status_code=400, detail="product_id is required")
        try:
            pid = UUID(pid_raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid product_id") from None
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="quantity must be an integer") from None
        if qty <= 0:
            raise HTTPException(status_code=400, detail="quantity must be positive")
        parsed_items.append({"product_id": pid, "quantity": qty})

    service = OrderService(db)
    result, status_code = await service.create_order(
        dc_id=dc_id,
        items=parsed_items,
        delivery_address=delivery_address,
        order_id=order_id,
    )

    if status_code == 404:
        raise HTTPException(status_code=404, detail="DC not found")

    if status_code == 409:
        # Return 409 with the partial/unavailable body
        return JSONResponse(status_code=409, content=result)

    return JSONResponse(status_code=status_code, content=result)


@router.get("/{order_id}")
async def get_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve an order with line items and current status."""
    try:
        oid = UUID(order_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Order not found") from None

    service = OrderService(db)
    result = await service.get_order(oid)
    if result is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return result


@router.post("/{order_id}/status")
async def advance_status(
    order_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Advance order through status lifecycle."""
    try:
        oid = UUID(order_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Order not found") from None

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body") from None

    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="status is required")

    service = OrderService(db)
    result = await service.advance_status(oid, new_status)
    if result is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if result.get("status") == "conflict":
        raise HTTPException(status_code=409, detail=result.get("detail", "Invalid transition"))
    # Commit before the response is sent (not after yield in get_db),
    # so subsequent requests see the updated status immediately.
    await db.commit()
    return result


@router.post("/{order_id}/cancel")
async def cancel_order(order_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel an order and release reserved inventory."""
    try:
        oid = UUID(order_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="Order not found") from None

    service = OrderService(db)
    result = await service.cancel_order(oid)
    if result is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if result.get("status") == "conflict":
        raise HTTPException(status_code=409, detail=result.get("detail", "Cannot cancel"))
    return result
