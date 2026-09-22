"""Redis hash queries for active online presence and session tracking."""

from typing import cast

import redis.asyncio as redis

from .errors import handle_redis_errors

REDIS_KEY = "active_user_counts"


@handle_redis_errors
async def add_active_user(client: redis.Redis, user_id: str) -> None:
    """Increments active connection counter for a user in Redis."""
    await client.hincrby(REDIS_KEY, user_id, 1)


@handle_redis_errors
async def remove_active_user(client: redis.Redis, user_id: str) -> None:
    """Decrements active connection counter and clears user when no connections remain."""
    count = await client.hincrby(REDIS_KEY, user_id, -1)
    if count <= 0:
        await client.hdel(REDIS_KEY, user_id)


@handle_redis_errors
async def get_active_users(client: redis.Redis) -> set[str]:
    """Retrieves the set of all currently active online user IDs from Redis."""
    users = await client.hkeys(REDIS_KEY)
    return set(cast(list[str], users))


@handle_redis_errors
async def invalidate_deleted_group_cache(
    client: redis.Redis, group_id: str, member_ids: list[str]
) -> None:
    """Cleans up Redis cache keys and user group mappings when a group is deleted."""
    async with client.pipeline(transaction=True) as pipe:
        pipe.delete(f"group:{group_id}", f"group:{group_id}:members")
        for member_id in member_ids:
            pipe.srem(f"user:{member_id}:groups", group_id)
        await pipe.execute()
