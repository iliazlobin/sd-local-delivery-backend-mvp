"""Order model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from local_delivery.db import Base

if TYPE_CHECKING:
    from local_delivery.models.order_line_item import OrderLineItem


class Order(Base):
    __tablename__ = "orders"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    dc_id: Mapped[str] = mapped_column(Text, ForeignKey("dcs.dc_id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="confirmed")
    total_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    line_items: Mapped[list["OrderLineItem"]] = relationship(back_populates="order", lazy="raise")
