#!/usr/bin/env python3
"""Start the app with SQLite for acceptance testing."""

import asyncio
import os
import sys

# Override DATABASE_URL to use SQLite
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./acceptance_test.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

# Add src to path
sys.path.insert(0, "/root/Hermes/projects/sd-local-delivery-backend-mvp-v2026.06.30.1/src")

from local_delivery.db import Base, get_engine


async def init_db():
    """Create all tables."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created")


async def main():
    await init_db()

    import uvicorn

    config = uvicorn.Config(
        "local_delivery.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
