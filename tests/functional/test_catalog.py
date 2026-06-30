"""Functional tests for catalog endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product


@pytest.mark.asyncio
async def test_category_browse_success(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Browsing a valid category returns 200 with items."""
    dc = DC(
        dc_id="PHL-01",
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
            dc_id="PHL-01",
            name="Chips",
            brand="Lays",
            category="snacks",
            unit_price_cents=399,
        )
    )
    db.add(Inventory(inventory_id=uuid.uuid4(), dc_id="PHL-01", product_id=pid, stock_on_hand=50))
    await db.flush()

    r = await client.get(
        "/v1/catalog",
        params={
            "dc_id": "PHL-01",
            "category": "snacks",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["available"] is True
    assert data["items"][0]["available_qty"] == 50


@pytest.mark.asyncio
async def test_category_browse_unknown_dc(client: AsyncClient) -> None:
    """Unknown DC returns 404."""
    r = await client.get(
        "/v1/catalog",
        params={
            "dc_id": "NONEXISTENT",
            "category": "snacks",
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_category_browse_missing_dc_id(client: AsyncClient) -> None:
    """Missing dc_id returns 400."""
    r = await client.get("/v1/catalog", params={"category": "snacks"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_text_search_success(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Text search returns matching items."""
    dc = DC(
        dc_id="PHL-01",
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
            dc_id="PHL-01",
            name="Tortilla Chips",
            brand="Brand",
            category="snacks",
            unit_price_cents=200,
        )
    )
    db.add(Inventory(inventory_id=uuid.uuid4(), dc_id="PHL-01", product_id=pid, stock_on_hand=10))
    await db.flush()

    r = await client.get(
        "/v1/catalog",
        params={
            "dc_id": "PHL-01",
            "q": "chips",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert "chips" in data["items"][0]["name"].lower()


@pytest.mark.asyncio
async def test_text_search_no_match(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Search with no matching items returns empty list."""
    dc = DC(
        dc_id="PHL-01",
        name="Test",
        center_lat=0,
        center_lon=0,
        delivery_radius_mi=100,
        status="active",
    )
    db.add(dc)
    await db.flush()

    r = await client.get(
        "/v1/catalog",
        params={
            "dc_id": "PHL-01",
            "q": "xyznonexistent",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_pagination(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Page 2 returns correct offset."""
    dc = DC(
        dc_id="PHL-01",
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
                dc_id="PHL-01",
                name=f"Item{i}",
                brand="B",
                category="snacks",
                unit_price_cents=100,
            )
        )
        db.add(
            Inventory(inventory_id=uuid.uuid4(), dc_id="PHL-01", product_id=pid, stock_on_hand=10)
        )
    await db.flush()

    p1 = await client.get(
        "/v1/catalog",
        params={
            "dc_id": "PHL-01",
            "page": 1,
            "page_size": 2,
        },
    )
    assert p1.status_code == 200
    d1 = p1.json()
    assert len(d1["items"]) == 2

    p2 = await client.get(
        "/v1/catalog",
        params={
            "dc_id": "PHL-01",
            "page": 2,
            "page_size": 2,
        },
    )
    assert p2.status_code == 200
    d2 = p2.json()
    assert len(d2["items"]) == 2
    # Items should differ
    ids_p1 = {i["product_id"] for i in d1["items"]}
    ids_p2 = {i["product_id"] for i in d2["items"]}
    assert ids_p1.isdisjoint(ids_p2)
