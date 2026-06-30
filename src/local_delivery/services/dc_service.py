"""DC lookup service — Haversine-based nearest DC finder."""

from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC


class DCService:
    """Service for DC geo-lookup using Haversine distance."""

    EARTH_RADIUS_MI = 3959.0

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def haversine_distance(
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
    ) -> float:
        """Calculate great-circle distance between two points in miles."""
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return DCService.EARTH_RADIUS_MI * c

    async def find_nearest(
        self,
        lat: float,
        lon: float,
    ) -> dict | None:
        """Find the nearest active DC that covers the given point.

        Returns a dict with dc_id, name, center_lat, center_lon, distance_mi,
        or None if no DC covers the location.
        """
        result = await self.db.execute(
            select(DC).where(DC.status == "active"),
        )
        dcs = result.scalars().all()

        best: dict | None = None
        best_distance = float("inf")

        for dc in dcs:
            distance = self.haversine_distance(
                lat,
                lon,
                dc.center_lat,
                dc.center_lon,
            )
            if distance <= dc.delivery_radius_mi and distance < best_distance:
                best_distance = distance
                best = {
                    "dc_id": dc.dc_id,
                    "name": dc.name,
                    "center_lat": dc.center_lat,
                    "center_lon": dc.center_lon,
                    "distance_mi": round(distance, 2),
                }

        return best
