"""Seed script: populate DCs, Products, and Inventory for the Local Delivery MVP."""

import asyncio
import os
import sys
import uuid

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from local_delivery.config import settings
from local_delivery.db import Base
from local_delivery.models.dc import DC
from local_delivery.models.inventory import Inventory
from local_delivery.models.product import Product

DC_DATA = [
    (
        "PHL-01",
        "Philadelphia Center City",
        39.9526,
        -75.1652,
        15.0,
        "active",
    ),
    (
        "PHL-02",
        "Philadelphia University City",
        39.9500,
        -75.2000,
        10.0,
        "active",
    ),
]

PRODUCT_DATA = [
    # Snacks
    ("Lay's Classic Potato Chips", "Lay's", "snacks", 399),
    ("Doritos Nacho Cheese Chips", "Doritos", "snacks", 449),
    ("Pringles Original Chips", "Pringles", "snacks", 299),
    ("Cheetos Crunchy Chips", "Cheetos", "snacks", 399),
    ("Tostitos Tortilla Chips", "Tostitos", "snacks", 379),
    ("Sun Chips Harvest Cheddar", "Sun Chips", "snacks", 429),
    ("Kettle Brand Sea Salt Chips", "Kettle", "snacks", 499),
    ("Ruffles Cheddar & Sour Cream Chips", "Ruffles", "snacks", 449),
    ("Miss Vickie's Jalapeno Chips", "Miss Vickie's", "snacks", 449),
    ("Cape Cod Original Chips", "Cape Cod", "snacks", 399),
    # Beverages
    ("Coca-Cola Classic", "Coca-Cola", "beverages", 199),
    ("Pepsi Cola", "Pepsi", "beverages", 199),
    ("Mountain Dew", "Pepsi", "beverages", 199),
    ("Dr Pepper", "Dr Pepper", "beverages", 199),
    ("Sprite Lemon-Lime", "Coca-Cola", "beverages", 199),
    ("Fanta Orange", "Coca-Cola", "beverages", 199),
    ("Canada Dry Ginger Ale", "Canada Dry", "beverages", 199),
    ("Arizona Iced Tea", "Arizona", "beverages", 99),
    ("Gatorade Cool Blue", "Gatorade", "beverages", 249),
    ("Monster Energy Original", "Monster", "beverages", 349),
    # Candy
    ("Snickers Bar", "Mars", "candy", 199),
    ("M&M's Milk Chocolate", "Mars", "candy", 199),
    ("Reese's Peanut Butter Cups", "Hershey", "candy", 199),
    ("Kit Kat Bar", "Nestle", "candy", 199),
    ("Twix Caramel Cookie", "Mars", "candy", 199),
    ("Skittles Original", "Mars", "candy", 199),
    ("Starburst Original", "Mars", "candy", 199),
    ("Hershey's Milk Chocolate Bar", "Hershey", "candy", 149),
    ("Sour Patch Kids", "Mondelez", "candy", 249),
    ("Swedish Fish", "Mondelez", "candy", 249),
    # Ice Cream
    ("Ben & Jerry's Choc Chip Cookie Dough", "Ben & Jerry's", "ice_cream", 599),
    ("Haagen-Dazs Vanilla", "Haagen-Dazs", "ice_cream", 549),
    ("Talenti Sea Salt Caramel Gelato", "Talenti", "ice_cream", 599),
    ("Magnum Classic Ice Cream Bars", "Magnum", "ice_cream", 499),
    ("Breyers Natural Vanilla", "Breyers", "ice_cream", 449),
    ("Blue Bell Homemade Vanilla", "Blue Bell", "ice_cream", 499),
    ("Klondike Original Bar", "Klondike", "ice_cream", 299),
    ("Drumstick Vanilla Cone", "Nestle", "ice_cream", 349),
    ("Outshine Fruit Bars Strawberry", "Outshine", "ice_cream", 449),
    ("Good Humor Strawberry Shortcake", "Good Humor", "ice_cream", 299),
]

STOCK_LEVELS = {"snacks": 50, "beverages": 100, "candy": 75, "ice_cream": 30}


async def seed() -> None:
    """Populate the database with DCs, products, and inventory."""
    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as session:
        for dc_id, name, lat, lon, radius, status in DC_DATA:
            existing = await session.get(DC, dc_id)
            if existing is None:
                session.add(
                    DC(
                        dc_id=dc_id,
                        name=name,
                        center_lat=lat,
                        center_lon=lon,
                        delivery_radius_mi=radius,
                        status=status,
                    )
                )
                print(f"  Created DC: {dc_id} — {name}")
            else:
                print(f"  DC already exists: {dc_id}")

        await session.flush()

        for dc_id, _, _, _, _, _ in DC_DATA:
            for name, brand, cat, price in PRODUCT_DATA:
                result = await session.execute(
                    select(Product).where(
                        Product.dc_id == dc_id,
                        Product.name == name,
                    ),
                )
                if result.scalar_one_or_none() is not None:
                    continue

                p = Product(
                    product_id=uuid.uuid4(),
                    dc_id=dc_id,
                    name=name,
                    brand=brand,
                    category=cat,
                    unit_price_cents=price,
                    is_active=True,
                )
                session.add(p)
                await session.flush()

                stock = STOCK_LEVELS.get(cat, 40)
                inv = Inventory(
                    inventory_id=uuid.uuid4(),
                    dc_id=dc_id,
                    product_id=p.product_id,
                    stock_on_hand=stock,
                    reserved_qty=0,
                    version=1,
                )
                session.add(inv)

        await session.commit()
        n_dcs = len(DC_DATA)
        n_prods = len(PRODUCT_DATA)
        print(f"\nSeed complete: {n_dcs} DCs, {n_prods} products each.")
        print(f"Total products: {n_dcs * n_prods}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
