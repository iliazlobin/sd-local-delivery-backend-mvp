"""Unit tests for Inventory service."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.order import Order
from local_delivery.models.order_line_item import OrderLineItem
from local_delivery.models.product import Product
from local_delivery.services.inventory_service import InventoryService


@pytest.mark.asyncio
async def test_reserve_increments_reserved_qty(db: AsyncSession) -> None:
    """Reserve increments the reserved_qty by the given amount."""
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
    inv = Inventory(
        inventory_id=uuid.uuid4(),
        dc_id="DC-1",
        product_id=pid,
        stock_on_hand=100,
        reserved_qty=0,
        version=1,
    )
    db.add(inv)
    await db.flush()

    service = InventoryService(db)
    await service.reserve("DC-1", pid, 5)
    await db.flush()
    await db.refresh(inv)

    assert inv.reserved_qty == 5


@pytest.mark.asyncio
async def test_release_decrements_reserved_qty(db: AsyncSession) -> None:
    """Release decrements the reserved_qty by the given amount."""
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
    inv = Inventory(
        inventory_id=uuid.uuid4(),
        dc_id="DC-1",
        product_id=pid,
        stock_on_hand=100,
        reserved_qty=10,
        version=1,
    )
    db.add(inv)
    await db.flush()

    service = InventoryService(db)
    await service.release("DC-1", pid, 3)
    await db.flush()
    await db.refresh(inv)

    assert inv.reserved_qty == 7


@pytest.mark.asyncio
async def test_sweep_cancels_expired_orders(db: AsyncSession) -> None:
    """Sweep cancels orders in confirmed status older than 15 minutes."""
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
            name="Item",
            brand="B",
            category="cat",
            unit_price_cents=100,
        )
    )
    db.add(
        Inventory(
            inventory_id=uuid.uuid4(),
            dc_id="DC-1",
            product_id=pid,
            stock_on_hand=50,
            reserved_qty=5,
        )
    )
    await db.flush()

    # Create an expired order (20 minutes ago)
    old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    oid = uuid.uuid4()
    order = Order(
        order_id=oid,
        user_id="anon",
        dc_id="DC-1",
        status="confirmed",
        total_amount_cents=100,
        delivery_address="addr",
        created_at=old_time,
        updated_at=old_time,
    )
    db.add(order)
    db.add(
        OrderLineItem(
            line_item_id=uuid.uuid4(),
            order_id=oid,
            product_id=pid,
            quantity=1,
            unit_price_cents=100,
        )
    )
    await db.flush()

    service = InventoryService(db)
    cancelled = await service.sweep()
    await db.flush()

    assert cancelled == 1

    # Verify order is now cancelled
    await db.refresh(order)
    assert order.status == "cancelled"


@pytest.mark.asyncio
async def test_sweep_ignores_recent_orders(db: AsyncSession) -> None:
    """Sweep does not cancel orders created within the last 15 minutes."""
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
            name="Item",
            brand="B",
            category="cat",
            unit_price_cents=100,
        )
    )
    db.add(
        Inventory(
            inventory_id=uuid.uuid4(),
            dc_id="DC-1",
            product_id=pid,
            stock_on_hand=50,
            reserved_qty=5,
        )
    )
    await db.flush()

    # Create a recent order (1 minute ago)
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    oid = uuid.uuid4()
    order = Order(
        order_id=oid,
        user_id="anon",
        dc_id="DC-1",
        status="confirmed",
        total_amount_cents=100,
        delivery_address="addr",
        created_at=recent,
        updated_at=recent,
    )
    db.add(order)
    db.add(
        OrderLineItem(
            line_item_id=uuid.uuid4(),
            order_id=oid,
            product_id=pid,
            quantity=1,
            unit_price_cents=100,
        )
    )
    await db.flush()

    service = InventoryService(db)
    cancelled = await service.sweep()
    await db.flush()

    assert cancelled == 0
    await db.refresh(order)
    assert order.status == "confirmed"
