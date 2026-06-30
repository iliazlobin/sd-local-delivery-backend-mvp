"""Test fixtures: async HTTP client, test database, mock Redis."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from local_delivery.db import Base, get_db
from local_delivery.main import create_app
from local_delivery.redis import get_redis


class FakeRedis:
    """A simple in-memory fake for Redis operations used by catalog service."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def aclose(self) -> None:
        pass


# ── White-box test database fixtures ──────────────────────────────────────


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Session-scoped async SQLite engine (in-memory, shared)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test session that rolls back everything at teardown."""
    async with test_engine.connect() as conn:
        async with conn.begin() as trans:
            session_factory = async_sessionmaker(
                bind=conn,
                class_=AsyncSession,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            async with session_factory() as session:
                yield session
            await trans.rollback()


# ── HTTP client for functional tests ──────────────────────────────────────


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """An httpx AsyncClient that talks directly to the FastAPI app.

    Overrides get_db to use the test session and get_redis to use FakeRedis.
    """
    app = create_app()
    fake_redis = FakeRedis()

    async def _get_test_db():
        yield db

    async def _get_fake_redis():
        return fake_redis

    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_redis] = _get_fake_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
