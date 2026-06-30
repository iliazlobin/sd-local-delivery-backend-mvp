"""FastAPI application factory with lifespan and router mounting."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from local_delivery.redis import close_redis
from local_delivery.routers import admin_router, catalog_router, dc_router, orders_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown: clean up Redis on exit."""
    yield
    await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local Delivery MVP",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse(content={"status": "ok"})

    # Mount routers
    app.include_router(dc_router)
    app.include_router(catalog_router)
    app.include_router(orders_router)
    app.include_router(admin_router)

    return app


app = create_app()
