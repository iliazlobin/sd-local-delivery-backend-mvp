"""Catalog service — browse and search products with availability."""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product


class CatalogService:
    """Service for catalog browsing and text search."""

    AVAILABILITY_TTL = 60  # seconds

    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    async def browse(
        self,
        dc_id: str,
        *,
        category: str | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 30,
    ) -> dict:
        """Browse or search products at a DC with availability information."""
        # Verify DC exists
        dc = await self.db.get(DC, dc_id)
        if dc is None:
            return None  # signal "not found"

        # Build base query
        stmt = select(Product).where(Product.dc_id == dc_id, Product.is_active.is_(True))

        if category:
            stmt = stmt.where(Product.category == category)

        if q:
            stmt = stmt.where(Product.name.ilike(f"%{q}%"))

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar()

        # Paginate
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        products = result.scalars().all()

        # Fetch availability from Redis cache
        items = []
        for p in products:
            available_qty = await self._get_available_qty(dc_id, p.product_id)
            items.append(
                {
                    "product_id": str(p.product_id),
                    "name": p.name,
                    "brand": p.brand,
                    "category": p.category,
                    "unit_price_cents": p.unit_price_cents,
                    "available_qty": available_qty,
                    "available": available_qty > 0,
                }
            )

        # For text search, sort in-stock items first
        if q:
            items.sort(key=lambda i: (not i["available"], i["name"]))

        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    async def _get_available_qty(self, dc_id: str, product_id) -> int:
        """Get available quantity from Redis cache or compute from DB."""
        cache_key = f"avail:{dc_id}:{product_id}"

        cached = await self.redis.get(cache_key)
        if cached is not None:
            return int(cached)

        # Cache miss — compute from DB
        result = await self.db.execute(
            select(Inventory).where(
                Inventory.dc_id == dc_id,
                Inventory.product_id == product_id,
            ),
        )
        inv = result.scalar_one_or_none()
        if inv is None:
            available = 0
        else:
            available = inv.stock_on_hand - inv.reserved_qty

        # Cache with TTL
        await self.redis.setex(cache_key, self.AVAILABILITY_TTL, str(available))
        return available
