"""Redis set queries for managing and retrieving active online user state."""

from typing import cast

from .connection import get_redis
from .errors import handle_redis_errors


@handle_redis_errors
async def add_active_user(user_id: str) -> None:
    """Adds a user ID to the set of active online users in Redis."""
    client = get_redis()
    async with client.pipeline(transaction=True) as pipe:
        pipe.sadd("active_users", user_id)
        await pipe.execute()


@handle_redis_errors
async def remove_active_user(user_id: str) -> None:
    """Removes a user ID from the set of active online users in Redis."""
    client = get_redis()
    async with client.pipeline(transaction=True) as pipe:
        pipe.srem("active_users", user_id)
        await pipe.execute()


@handle_redis_errors
async def get_active_users() -> set[str]:
    """Retrieves the set of all currently active online user IDs from Redis."""
    client = get_redis()
    users = await client.smembers("active_users")
    return cast(set[str], users)
