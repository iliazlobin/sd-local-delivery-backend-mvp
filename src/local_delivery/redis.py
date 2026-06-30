"""Redis client dependency — async, lazily created."""

from __future__ import annotations

from redis.asyncio import Redis

from local_delivery.config import settings

_client: Redis | None = None


async def get_redis() -> Redis:
    """Return a shared async Redis client, creating it on first call."""
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    """Close the shared Redis client if it was opened."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
