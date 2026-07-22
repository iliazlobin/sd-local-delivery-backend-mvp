"""Order service — create, retrieve, advance status, cancel orders."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.order import Order
from local_delivery.models.order_line_item import OrderLineItem
from local_delivery.models.product import Product
from local_delivery.services.inventory_service import InventoryService

_VALID_TRANSITIONS: dict[str, list[str]] = {
    "confirmed": ["picking"],
    "picking": ["packed", "cancelled"],
    "packed": ["en_route"],
    "en_route": ["delivered"],
    "delivered": [],
    "cancelled": [],
}


def _lifecycle_order(status: str) -> int:
    """Return the lifecycle position for comparison."""
    order = ["confirmed", "picking", "packed", "en_route", "delivered", "cancelled"]
    try:
        return order.index(status)
    except ValueError:
        return -1


class OrderService:
    """Service for order lifecycle management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_order(
        self,
        dc_id: str,
        items: list[dict],
        delivery_address: str,
        order_id,
    ) -> tuple[dict | None, int]:
        """Create an order with atomic inventory reservation.

        Returns a tuple of (result_dict, http_status_code).
        http_status_code will be 201 for new orders, 200 for idempotent duplicates,
        409 for partial stock, 404 for unknown DC.
        result_dict will be None if DC is not found.
        """
        # Check DC exists
        dc = await self.db.get(DC, dc_id)
        if dc is None:
            return None, 404

        # Idempotency check
        existing = await self.db.get(
            Order,
            order_id,
            options=[selectinload(Order.line_items)],
        )
        if existing is not None:
            return self._order_to_response(existing), 200

        # Collect product IDs and lock inventory rows in product_id order
        product_ids = sorted(item["product_id"] for item in items)

        # Verify all products exist at this DC and fetch them
        products_map: dict = {}
        for pid in product_ids:
            result = await self.db.execute(
                select(Product).where(
                    Product.product_id == pid,
                    Product.dc_id == dc_id,
                    Product.is_active.is_(True),
                ),
            )
            product = result.scalar_one_or_none()
            if product is None:
                products_map[pid] = None
            else:
                products_map[pid] = product

        # Lock inventory rows in product_id order (pessimistic row-locking)
        inventory_map: dict = {}
        for pid in product_ids:
            result = await self.db.execute(
                select(Inventory)
                .where(Inventory.dc_id == dc_id, Inventory.product_id == pid)
                .with_for_update(),
            )
            inv = result.scalar_one_or_none()
            inventory_map[pid] = inv

        # Check availability
        unavailable: list[dict] = []
        available_items: list[dict] = []

        for item in items:
            pid = item["product_id"]
            qty = item["quantity"]
            product = products_map.get(pid)
            inv = inventory_map.get(pid)

            if product is None:
                unavailable.append(
                    {
                        "product_id": str(pid),
                        "quantity_available": 0,
                    }
                )
                continue

            if inv is None:
                available_on_hand = 0
            else:
                available_on_hand = inv.stock_on_hand - inv.reserved_qty

            if available_on_hand < qty:
                unavailable.append(
                    {
                        "product_id": str(pid),
                        "quantity_available": available_on_hand,
                    }
                )
            else:
                available_items.append(
                    {
                        "product_id": pid,
                        "quantity": qty,
                        "unit_price_cents": product.unit_price_cents,
                        "name": product.name,
                    }
                )

        if unavailable:
            # Don't reserve anything on partial stock
            return {
                "status": "partial",
                "unavailable": unavailable,
            }, 409

        # All items available — reserve inventory and create the order
        inv_service = InventoryService(self.db)
        for item in available_items:
            await inv_service.reserve(dc_id, item["product_id"], item["quantity"])

        # Calculate total
        total_cents = sum(inv["unit_price_cents"] * inv["quantity"] for inv in available_items)

        now = datetime.now(timezone.utc)
        order = Order(
            order_id=order_id,
            user_id="anonymous",
            dc_id=dc_id,
            status="confirmed",
            total_amount_cents=total_cents,
            delivery_address=delivery_address,
            created_at=now,
            updated_at=now,
        )
        self.db.add(order)

        line_items_response = []
        for item in available_items:
            li = OrderLineItem(
                order_id=order_id,
                product_id=item["product_id"],
                quantity=item["quantity"],
                unit_price_cents=item["unit_price_cents"],
            )
            self.db.add(li)
            line_items_response.append(
                {
                    "product_id": str(item["product_id"]),
                    "name": item["name"],
                    "quantity": item["quantity"],
                    "unit_price_cents": item["unit_price_cents"],
                }
            )

        await self.db.flush()
        await self.db.commit()

        return {
            "order_id": str(order_id),
            "status": "confirmed",
            "items": line_items_response,
            "total_amount_cents": total_cents,
            "delivery_address": delivery_address,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }, 201

    async def get_order(self, order_id) -> dict | None:
        """Retrieve an order with line items."""
        result = await self.db.execute(
            select(Order).where(Order.order_id == order_id).options(selectinload(Order.line_items)),
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None
        return self._order_to_response(order)

    async def advance_status(self, order_id, new_status: str) -> dict | None:
        """Advance an order through the status lifecycle.

        Returns the updated order dict, a conflict dict for invalid transitions,
        or None if order not found.
        """
        result = await self.db.execute(
            select(Order).where(Order.order_id == order_id),
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None

        current = order.status
        allowed = _VALID_TRANSITIONS.get(current, [])

        if new_status not in allowed:
            detail = f"Cannot transition from {current} to {new_status}"
            return {"status": "conflict", "detail": detail}

        order.status = new_status
        order.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.commit()

        return {"status": new_status}

    async def cancel_order(self, order_id) -> dict | None:
        """Cancel an order and release reservations.

        Returns the result dict, or None if order not found.
        """
        result = await self.db.execute(
            select(Order).where(Order.order_id == order_id).options(selectinload(Order.line_items)),
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None

        if order.status not in ("confirmed", "picking"):
            return {
                "status": "conflict",
                "detail": f"Cannot cancel order in status {order.status}",
            }

        # Release reservations for all line items
        inv_service = InventoryService(self.db)
        for item in order.line_items:
            await inv_service.release(order.dc_id, item.product_id, item.quantity)

        order.status = "cancelled"
        order.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.commit()

        return {
            "order_id": str(order_id),
            "status": "cancelled",
            "updated_at": order.updated_at.isoformat(),
        }

    def _order_to_response(self, order: Order) -> dict:
        """Convert an Order ORM object to the API response dict."""
        items = []
        for li in order.line_items:
            items.append(
                {
                    "product_id": str(li.product_id),
                    "name": li.product.name if li.product else "",
                    "quantity": li.quantity,
                    "unit_price_cents": li.unit_price_cents,
                }
            )
        return {
            "order_id": str(order.order_id),
            "status": order.status,
            "items": items,
            "total_amount_cents": order.total_amount_cents,
            "delivery_address": order.delivery_address,
            "created_at": order.created_at.isoformat() if order.created_at else "",
            "updated_at": order.updated_at.isoformat() if order.updated_at else "",
        }
