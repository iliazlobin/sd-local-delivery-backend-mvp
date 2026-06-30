"""Inventory model."""

from __future__ import annotations

import uuid

from sqlalchemy import UUID, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from local_delivery.db import Base


class Inventory(Base):
    __tablename__ = "inventory"

    inventory_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    dc_id: Mapped[str] = mapped_column(Text, ForeignKey("dcs.dc_id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("products.product_id"), nullable=False
    )
    stock_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (UniqueConstraint("dc_id", "product_id"),)
