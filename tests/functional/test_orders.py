"""Functional tests for order endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product


async def _seed_catalog(db: AsyncSession) -> tuple[str, uuid.UUID]:
    """Create a DC and product. Return (dc_id, product_id)."""
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
            name="Product",
            brand="B",
            category="cat",
            unit_price_cents=500,
        )
    )
    db.add(Inventory(inventory_id=uuid.uuid4(), dc_id="PHL-01", product_id=pid, stock_on_hand=50))
    await db.flush()
    return "PHL-01", pid


@pytest.mark.asyncio
async def test_create_order_success(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Valid order returns 201 with confirmed status."""
    dc_id, pid = await _seed_catalog(db)
    oid = str(uuid.uuid4())

    r = await client.post(
        "/v1/orders",
        json={
            "dc_id": dc_id,
            "items": [{"product_id": str(pid), "quantity": 2}],
            "delivery_address": "123 Test St",
            "order_id": oid,
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["order_id"] == oid
    assert data["status"] == "confirmed"
    assert data["total_amount_cents"] == 1000


@pytest.mark.asyncio
async def test_order_idempotent(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Duplicate order_id returns 200."""
    dc_id, pid = await _seed_catalog(db)
    oid = str(uuid.uuid4())

    r1 = await client.post(
        "/v1/orders",
        json={
            "dc_id": dc_id,
            "items": [{"product_id": str(pid), "quantity": 1}],
            "delivery_address": "addr",
            "order_id": oid,
        },
    )
    assert r1.status_code == 201

    r2 = await client.post(
        "/v1/orders",
        json={
            "dc_id": dc_id,
            "items": [{"product_id": str(pid), "quantity": 1}],
            "delivery_address": "addr",
            "order_id": oid,
        },
    )
    assert r2.status_code == 200
    assert r2.json()["order_id"] == oid


@pytest.mark.asyncio
async def test_order_partial_stock(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Requesting > available stock returns 409 with partial."""
    dc_id, pid = await _seed_catalog(db)
    oid = str(uuid.uuid4())

    r = await client.post(
        "/v1/orders",
        json={
            "dc_id": dc_id,
            "items": [{"product_id": str(pid), "quantity": 99999}],
            "delivery_address": "addr",
            "order_id": oid,
        },
    )
    assert r.status_code == 409
    data = r.json()
    assert data["status"] == "partial"
    assert len(data["unavailable"]) == 1


@pytest.mark.asyncio
async def test_order_missing_dc_id(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Missing dc_id returns 400."""
    _, pid = await _seed_catalog(db)
    r = await client.post(
        "/v1/orders",
        json={
            "items": [{"product_id": str(pid), "quantity": 1}],
            "delivery_address": "addr",
            "order_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_order_unknown_dc(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Unknown DC returns 404."""
    _, pid = await _seed_catalog(db)
    r = await client.post(
        "/v1/orders",
        json={
            "dc_id": "NONEXISTENT",
            "items": [{"product_id": str(pid), "quantity": 1}],
            "delivery_address": "addr",
            "order_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_order_success(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Get existing order returns 200."""
    dc_id, pid = await _seed_catalog(db)
    oid = str(uuid.uuid4())

    await client.post(
        "/v1/orders",
        json={
            "dc_id": dc_id,
            "items": [{"product_id": str(pid), "quantity": 1}],
            "delivery_address": "addr",
            "order_id": oid,
        },
    )

    r = await client.get(f"/v1/orders/{oid}")
    assert r.status_code == 200
    data = r.json()
    assert data["order_id"] == oid
    assert data["status"] == "confirmed"
    assert "items" in data


@pytest.mark.asyncio
async def test_get_order_not_found(client: AsyncClient) -> None:
    """Unknown order returns 404."""
    r = await client.get(f"/v1/orders/{uuid.uuid4()}")
    assert r.status_code == 404
