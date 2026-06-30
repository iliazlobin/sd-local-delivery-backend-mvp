"""DC lookup schemas."""

from __future__ import annotations

from pydantic import BaseModel


class DCLookupResponse(BaseModel):
    dc_id: str
    name: str
    center_lat: float
    center_lon: float
    distance_mi: float
