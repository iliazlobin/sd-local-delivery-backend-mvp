"""Unit tests for Order service."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product
from local_delivery.services.order_service import OrderService


async def _setup_dc_and_product(db: AsyncSession) -> tuple[str, uuid.UUID]:
    """Create a DC and a product with 100 stock. Return (dc_id, product_id)."""
    dc = DC(
        dc_id="DC-1",
        name="Test",
        center_lat=0,
        center_lon=0,
        delivery_radius_mi=100,
        status="active",
    )
    db.add(dc)
    await db.flush()

    pid = uuid.uuid4()
    db.add(
        Product(
            product_id=pid,
            dc_id="DC-1",
            name="Test Product",
            brand="TestBrand",
            category="test",
            unit_price_cents=500,
        )
    )
    db.add(
        Inventory(
            inventory_id=uuid.uuid4(),
            dc_id="DC-1",
            product_id=pid,
            stock_on_hand=100,
            reserved_qty=0,
        )
    )
    await db.flush()
    return "DC-1", pid


@pytest.mark.asyncio
async def test_create_order_success(db: AsyncSession) -> None:
    """Valid order creation returns 201 with confirmed status."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    result, status = await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 2}],
        delivery_address="123 Test St",
        order_id=oid,
    )
    assert status == 201
    assert result["status"] == "confirmed"
    assert result["total_amount_cents"] == 1000  # 500 * 2
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_create_order_idempotent(db: AsyncSession) -> None:
    """Duplicate order_id returns 200, not double-reserving."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    _, s1 = await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )
    assert s1 == 201

    _, s2 = await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 5}],
        delivery_address="addr",
        order_id=oid,
    )
    assert s2 == 200


@pytest.mark.asyncio
async def test_create_order_partial_stock(db: AsyncSession) -> None:
    """Requesting more than available returns 409 with unavailable list."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    result, status = await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 99999}],
        delivery_address="addr",
        order_id=oid,
    )
    assert status == 409
    assert result["status"] == "partial"
    assert len(result["unavailable"]) == 1
    assert result["unavailable"][0]["product_id"] == str(pid)


@pytest.mark.asyncio
async def test_create_order_unknown_dc(db: AsyncSession) -> None:
    """Unknown DC returns 404."""
    service = OrderService(db)
    oid = uuid.uuid4()
    result, status = await service.create_order(
        dc_id="NONEXISTENT",
        items=[{"product_id": uuid.uuid4(), "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )
    assert status == 404
    assert result is None


@pytest.mark.asyncio
async def test_get_order_success(db: AsyncSession) -> None:
    """Get existing order returns full shape with items."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )

    result = await service.get_order(oid)
    assert result is not None
    assert result["status"] == "confirmed"
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_get_order_not_found(db: AsyncSession) -> None:
    """Unknown order returns None."""
    service = OrderService(db)
    result = await service.get_order(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_advance_status_full_lifecycle(db: AsyncSession) -> None:
    """Valid transitions return updated status."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )

    for expected in ("picking", "packed", "en_route", "delivered"):
        result = await service.advance_status(oid, expected)
        assert result is not None
        assert result.get("status") == expected


@pytest.mark.asyncio
async def test_advance_status_skip_rejected(db: AsyncSession) -> None:
    """Skipping a state returns conflict."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )

    result = await service.advance_status(oid, "packed")
    assert result["status"] == "conflict"


@pytest.mark.asyncio
async def test_cancel_order_success(db: AsyncSession) -> None:
    """Cancel a confirmed order returns cancelled status."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )

    result = await service.cancel_order(oid)
    assert result["status"] == "cancelled"
    assert result["order_id"] == str(oid)


@pytest.mark.asyncio
async def test_cancel_order_releases_inventory(db: AsyncSession) -> None:
    """Cancelling an order decrements reserved_qty."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 3}],
        delivery_address="addr",
        order_id=oid,
    )

    await service.cancel_order(oid)

    # Check inventory was released
    from sqlalchemy import select

    from local_delivery.models.inventory import Inventory

    result = await db.execute(
        select(Inventory).where(Inventory.dc_id == dc_id, Inventory.product_id == pid),
    )
    inv = result.scalar_one()
    assert inv.reserved_qty == 0


@pytest.mark.asyncio
async def test_cancel_packed_order_rejected(db: AsyncSession) -> None:
    """Cannot cancel a packed order."""
    dc_id, pid = await _setup_dc_and_product(db)
    service = OrderService(db)

    oid = uuid.uuid4()
    await service.create_order(
        dc_id=dc_id,
        items=[{"product_id": pid, "quantity": 1}],
        delivery_address="addr",
        order_id=oid,
    )
    await service.advance_status(oid, "picking")
    await service.advance_status(oid, "packed")

    result = await service.cancel_order(oid)
    assert result["status"] == "conflict"
