"""OrderLineItem model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import UUID, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from local_delivery.db import Base

if TYPE_CHECKING:
    from local_delivery.models.order import Order
    from local_delivery.models.product import Product


class OrderLineItem(Base):
    __tablename__ = "order_line_items"

    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("orders.order_id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("products.product_id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="line_items")
    product: Mapped["Product"] = relationship(lazy="joined")
