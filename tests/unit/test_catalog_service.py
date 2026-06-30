"""Unit tests for Catalog service."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product
from tests.conftest import FakeRedis


@pytest.mark.asyncio
async def test_browse_returns_products(db: AsyncSession) -> None:
    """Browsing a valid DC with a category returns products."""
    dc = DC(
        dc_id="DC-1",
        name="Test DC",
        center_lat=0,
        center_lon=0,
        delivery_radius_mi=100,
        status="active",
    )
    db.add(dc)
    await db.flush()

    pid = uuid.uuid4()
    p = Product(
        product_id=pid,
        dc_id="DC-1",
        name="Chips",
        brand="Lays",
        category="snacks",
        unit_price_cents=399,
        is_active=True,
    )
    db.add(p)
    inv = Inventory(
        inventory_id=uuid.uuid4(),
        dc_id="DC-1",
        product_id=pid,
        stock_on_hand=50,
        reserved_qty=0,
        version=1,
    )
    db.add(inv)
    await db.flush()

    from local_delivery.services.catalog_service import CatalogService

    redis = FakeRedis()
    service = CatalogService(db, redis)
    result = await service.browse(dc_id="DC-1", category="snacks")
    assert result is not None
    assert len(result["items"]) == 1
    assert result["items"][0]["available_qty"] == 50
    assert result["items"][0]["available"] is True
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_browse_unknown_dc_returns_none(db: AsyncSession) -> None:
    """Browsing an unknown DC returns None."""
    from local_delivery.services.catalog_service import CatalogService

    redis = FakeRedis()
    service = CatalogService(db, redis)
    result = await service.browse(dc_id="NONEXISTENT", category="snacks")
    assert result is None


@pytest.mark.asyncio
async def test_browse_respects_pagination(db: AsyncSession) -> None:
    """Pagination returns correct page size and offsets."""
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

    for i in range(5):
        pid = uuid.uuid4()
        db.add(
            Product(
                product_id=pid,
                dc_id="DC-1",
                name=f"Item {i}",
                brand="B",
                category="snacks",
                unit_price_cents=100,
            )
        )
        db.add(Inventory(inventory_id=uuid.uuid4(), dc_id="DC-1", product_id=pid, stock_on_hand=10))
    await db.flush()

    from local_delivery.services.catalog_service import CatalogService

    redis = FakeRedis()
    service = CatalogService(db, redis)

    page1 = await service.browse(dc_id="DC-1", page=1, page_size=2)
    assert len(page1["items"]) == 2
    assert page1["total"] == 5

    page3 = await service.browse(dc_id="DC-1", page=3, page_size=2)
    assert len(page3["items"]) == 1
    assert page3["total"] == 5


@pytest.mark.asyncio
async def test_text_search_iliqe(db: AsyncSession) -> None:
    """ILIKE search matches case-insensitively."""
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
            name="Spicy CHIPS",
            brand="B",
            category="snacks",
            unit_price_cents=100,
        )
    )
    db.add(Inventory(inventory_id=uuid.uuid4(), dc_id="DC-1", product_id=pid, stock_on_hand=10))
    await db.flush()

    from local_delivery.services.catalog_service import CatalogService

    redis = FakeRedis()
    service = CatalogService(db, redis)

    r1 = await service.browse(dc_id="DC-1", q="chips")
    assert r1["total"] == 1

    r2 = await service.browse(dc_id="DC-1", q="CHIPS")
    assert r2["total"] == 1

    r3 = await service.browse(dc_id="DC-1", q="Chips")
    assert r3["total"] == 1


@pytest.mark.asyncio
async def test_text_search_in_stock_first(db: AsyncSession) -> None:
    """In-stock items appear before out-of-stock in search results."""
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

    pid1 = uuid.uuid4()
    db.add(
        Product(
            product_id=pid1,
            dc_id="DC-1",
            name="Chips A",
            brand="B",
            category="snacks",
            unit_price_cents=100,
        )
    )
    db.add(
        Inventory(
            inventory_id=uuid.uuid4(),
            dc_id="DC-1",
            product_id=pid1,
            stock_on_hand=0,
            reserved_qty=0,
        )
    )

    pid2 = uuid.uuid4()
    db.add(
        Product(
            product_id=pid2,
            dc_id="DC-1",
            name="Chips B",
            brand="B",
            category="snacks",
            unit_price_cents=100,
        )
    )
    db.add(
        Inventory(
            inventory_id=uuid.uuid4(),
            dc_id="DC-1",
            product_id=pid2,
            stock_on_hand=10,
            reserved_qty=0,
        )
    )
    await db.flush()

    from local_delivery.services.catalog_service import CatalogService

    redis = FakeRedis()
    service = CatalogService(db, redis)

    result = await service.browse(dc_id="DC-1", q="Chips")
    assert len(result["items"]) == 2
    # First item should be in stock
    assert result["items"][0]["available"] is True


@pytest.mark.asyncio
async def test_catalog_uses_redis_cache(db: AsyncSession) -> None:
    """Availability is cached in Redis after first lookup."""
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
            stock_on_hand=42,
            reserved_qty=0,
        )
    )
    await db.flush()

    from local_delivery.services.catalog_service import CatalogService

    redis = FakeRedis()

    # First call — should populate cache
    service = CatalogService(db, redis)
    result = await service.browse(dc_id="DC-1")
    assert result["items"][0]["available_qty"] == 42

    # Verify cache was populated
    cached = await redis.get(f"avail:DC-1:{pid}")
    assert cached == "42"

    # Second call with different DB state but cached value
    # (In real usage, cache would be used; for unit test we just verify caching works)
