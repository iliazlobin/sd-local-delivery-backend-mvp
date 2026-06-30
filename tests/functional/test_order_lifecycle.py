"""Functional tests for order lifecycle (advance status, cancel)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product


async def _create_order(client: AsyncClient, db: AsyncSession) -> str:
    """Create an order and return the order_id."""
    dc = DC(
        dc_id="PHL-01",
        name="Test",
        center_lat=0,
        center_lon=0,
        delivery_radius_mi=100,
        status="active",
    )
    db.add(dc)
    pid = uuid.uuid4()
    db.add(
        Product(
            product_id=pid,
            dc_id="PHL-01",
            name="Item",
            brand="B",
            category="cat",
            unit_price_cents=100,
        )
    )
    db.add(Inventory(inventory_id=uuid.uuid4(), dc_id="PHL-01", product_id=pid, stock_on_hand=50))
    await db.flush()

    oid = str(uuid.uuid4())
    r = await client.post(
        "/v1/orders",
        json={
            "dc_id": "PHL-01",
            "items": [{"product_id": str(pid), "quantity": 1}],
            "delivery_address": "addr",
            "order_id": oid,
        },
    )
    assert r.status_code == 201
    return oid


@pytest.mark.asyncio
async def test_advance_status_single_step(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Advancing from confirmed to picking returns 200."""
    oid = await _create_order(client, db)
    r = await client.post(f"/v1/orders/{oid}/status", json={"status": "picking"})
    assert r.status_code == 200
    assert r.json()["status"] == "picking"


@pytest.mark.asyncio
async def test_advance_status_full_lifecycle(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Walk full lifecycle: confirmed → delivered."""
    oid = await _create_order(client, db)
    for expected in ("picking", "packed", "en_route", "delivered"):
        r = await client.post(f"/v1/orders/{oid}/status", json={"status": expected})
        assert r.status_code == 200
        assert r.json()["status"] == expected


@pytest.mark.asyncio
async def test_advance_status_skip_rejected(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Skipping a state returns 409."""
    oid = await _create_order(client, db)
    r = await client.post(f"/v1/orders/{oid}/status", json={"status": "packed"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_advance_status_unknown_order(client: AsyncClient) -> None:
    """Advancing unknown order returns 404."""
    r = await client.post(f"/v1/orders/{uuid.uuid4()}/status", json={"status": "picking"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cancel_order_success(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Cancel a confirmed order returns 200 and sets cancelled."""
    oid = await _create_order(client, db)
    r = await client.post(f"/v1/orders/{oid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_order_already_cancelled(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Cancelling already cancelled order returns 409."""
    oid = await _create_order(client, db)
    await client.post(f"/v1/orders/{oid}/cancel")
    r = await client.post(f"/v1/orders/{oid}/cancel")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cancel_packed_order_rejected(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """Cannot cancel packed order."""
    oid = await _create_order(client, db)
    await client.post(f"/v1/orders/{oid}/status", json={"status": "picking"})
    await client.post(f"/v1/orders/{oid}/status", json={"status": "packed"})
    r = await client.post(f"/v1/orders/{oid}/cancel")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_cancel_order_unknown(client: AsyncClient) -> None:
    """Cancel unknown order returns 404."""
    r = await client.post(f"/v1/orders/{uuid.uuid4()}/cancel")
    assert r.status_code == 404
