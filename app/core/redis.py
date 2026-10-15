from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def redis_client() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def get_redis() -> Redis:
    return redis_client()


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
