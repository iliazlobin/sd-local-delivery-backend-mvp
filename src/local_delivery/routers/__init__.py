"""Routers for Local Delivery MVP."""

from local_delivery.routers.admin import router as admin_router
from local_delivery.routers.catalog import router as catalog_router
from local_delivery.routers.dc import router as dc_router
from local_delivery.routers.orders import router as orders_router

__all__ = ["admin_router", "catalog_router", "dc_router", "orders_router"]
