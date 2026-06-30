"""Distribution Center model."""

from __future__ import annotations

from sqlalchemy import Double, Text
from sqlalchemy.orm import Mapped, mapped_column

from local_delivery.db import Base


class DC(Base):
    __tablename__ = "dcs"

    dc_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    center_lat: Mapped[float] = mapped_column(Double, nullable=False)
    center_lon: Mapped[float] = mapped_column(Double, nullable=False)
    delivery_radius_mi: Mapped[float] = mapped_column(Double, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
