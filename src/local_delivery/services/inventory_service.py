"""Inventory service — reserve, release, and sweep inventory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.inventory import Inventory
from local_delivery.models.order import Order
from local_delivery.models.order_line_item import OrderLineItem


class InventoryService:
    """Service for inventory reservation and release."""

    SWEEP_TTL_MINUTES = 15

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def reserve(self, dc_id: str, product_id, qty: int) -> None:
        """Reserve qty units of a product at a DC.

        Caller must have locked the inventory row with FOR UPDATE.
        """
        await self.db.execute(
            update(Inventory)
            .where(
                Inventory.dc_id == dc_id,
                Inventory.product_id == product_id,
            )
            .values(reserved_qty=Inventory.reserved_qty + qty),
        )

    async def release(self, dc_id: str, product_id, qty: int) -> None:
        """Release qty reserved units back to available stock."""
        await self.db.execute(
            update(Inventory)
            .where(
                Inventory.dc_id == dc_id,
                Inventory.product_id == product_id,
            )
            .values(reserved_qty=Inventory.reserved_qty - qty),
        )

    async def sweep(self) -> int:
        """Cancel expired confirmed orders and release their reservations.

        Returns the number of orders cancelled.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.SWEEP_TTL_MINUTES)

        # Find expired confirmed orders
        result = await self.db.execute(
            select(Order).where(
                Order.status == "confirmed",
                Order.created_at < cutoff,
            ),
        )
        expired_orders = result.scalars().all()

        cancelled_count = 0
        for order in expired_orders:
            # Get line items to release reservations
            items_result = await self.db.execute(
                select(OrderLineItem).where(OrderLineItem.order_id == order.order_id),
            )
            line_items = items_result.scalars().all()

            # Release each line item's reservation
            for item in line_items:
                await self.release(order.dc_id, item.product_id, item.quantity)

            # Mark order as cancelled
            order.status = "cancelled"
            order.updated_at = datetime.now(timezone.utc)
            cancelled_count += 1

        await self.db.flush()
        return cancelled_count
