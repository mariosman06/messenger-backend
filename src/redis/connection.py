"""Redis connection lifecycle management and global client access."""

import logging

import redis.asyncio as redis

from .errors import RedisClientNotInitializedError, handle_redis_errors

logger = logging.getLogger(__name__)

_pool: redis.ConnectionPool | None = None
_client: redis.Redis | None = None


@handle_redis_errors
async def init_redis(url: str) -> redis.Redis:
    """Initializes the global Redis connection pool and async client instance."""
    global _pool, _client
    if _client is None:
        logger.info("Initializing Redis connection pool targeting %s", url)
        _pool = redis.ConnectionPool.from_url(url, decode_responses=True, max_connections=70)
        _client = redis.Redis(connection_pool=_pool)
        await _client.ping()
        logger.info("Redis connection pool established successfully.")
    return _client


@handle_redis_errors
async def close_redis() -> None:
    """Closes active Redis client sessions and tears down the connection pool."""
    global _pool, _client
    if _client:
        await _client.aclose()
        _client = None
    if _pool:
        await _pool.aclose()
        _pool = None
    logger.info("Redis connection pool and client closed.")


def get_redis() -> redis.Redis:
    """Retrieves the initialized global Redis client instance."""
    if _client is None:
        logger.error("Attempted to access uninitialized Redis client.")
        raise RedisClientNotInitializedError()
    return _client
