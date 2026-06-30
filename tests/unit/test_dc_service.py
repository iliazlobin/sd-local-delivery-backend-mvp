"""Unit tests for DC service — Haversine distance + DB lookup."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.services.dc_service import DCService


def test_haversine_same_point_zero_distance() -> None:
    """Haversine distance for the same point should be 0."""
    distance = DCService.haversine_distance(39.9526, -75.1652, 39.9526, -75.1652)
    assert distance == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance_phl_to_nyc() -> None:
    """Distance from Philadelphia to NYC should be approximately 80 miles."""
    phl_lat, phl_lon = 39.9526, -75.1652
    nyc_lat, nyc_lon = 40.7128, -74.0060
    distance = DCService.haversine_distance(phl_lat, phl_lon, nyc_lat, nyc_lon)
    assert 75.0 < distance < 85.0


def test_haversine_short_distance_center_city() -> None:
    """Distance within Philadelphia Center City should be ~1-2 miles."""
    distance = DCService.haversine_distance(39.95, -75.16, 39.9526, -75.1652)
    assert 0.1 < distance < 3.0


@pytest.mark.asyncio
async def test_find_nearest_returns_dc_within_radius(db: AsyncSession) -> None:
    """Find nearest active DC that covers the given point."""
    dc = DC(
        dc_id="TEST-01",
        name="Test DC",
        center_lat=39.95,
        center_lon=-75.16,
        delivery_radius_mi=15.0,
        status="active",
    )
    db.add(dc)
    await db.flush()

    service = DCService(db)
    result = await service.find_nearest(39.95, -75.16)
    assert result is not None
    assert result["dc_id"] == "TEST-01"
    assert result["distance_mi"] == pytest.approx(0.0, abs=0.1)


@pytest.mark.asyncio
async def test_find_nearest_outside_radius(db: AsyncSession) -> None:
    """Point outside all DC radii returns None."""
    dc = DC(
        dc_id="FAR-01",
        name="Far DC",
        center_lat=40.0,
        center_lon=-75.0,
        delivery_radius_mi=1.0,
        status="active",
    )
    db.add(dc)
    await db.flush()

    service = DCService(db)
    result = await service.find_nearest(39.0, -76.0)
    assert result is None


@pytest.mark.asyncio
async def test_find_nearest_ignores_inactive(db: AsyncSession) -> None:
    """Inactive DCs should be ignored."""
    dc = DC(
        dc_id="INACTIVE",
        name="Offline DC",
        center_lat=39.95,
        center_lon=-75.16,
        delivery_radius_mi=100.0,
        status="inactive",
    )
    db.add(dc)
    await db.flush()

    service = DCService(db)
    result = await service.find_nearest(39.95, -75.16)
    assert result is None


@pytest.mark.asyncio
async def test_find_nearest_picks_closest(db: AsyncSession) -> None:
    """When multiple DCs cover a point, the nearest is returned."""
    dc1 = DC(
        dc_id="NEAR",
        name="Near DC",
        center_lat=39.95,
        center_lon=-75.16,
        delivery_radius_mi=100.0,
        status="active",
    )
    dc2 = DC(
        dc_id="FAR",
        name="Far DC",
        center_lat=40.0,
        center_lon=-75.0,
        delivery_radius_mi=100.0,
        status="active",
    )
    db.add_all([dc1, dc2])
    await db.flush()

    service = DCService(db)
    result = await service.find_nearest(39.95, -75.16)
    assert result is not None
    assert result["dc_id"] == "NEAR"
