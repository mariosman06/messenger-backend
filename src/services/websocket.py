"""Manages local WebSocket connections, Redis user tracking, and Pub/Sub delivery."""

import asyncio
from collections import defaultdict
from typing import Any
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import get_conn
from src.redis.events import RedisEvent
from src.redis.pubsub import listen_and_dispatch_message, publish_ws_push
from src.redis.queries import add_active_user, get_active_users, remove_active_user

CHANNEL_NAME = "ws_pushes"

# In-memory tracking tables for local node connections
_local_connections: dict[UUID, Any] = {}
_group_connections: dict[UUID, set[UUID]] = defaultdict(set)
_user_groups: dict[UUID, set[UUID]] = defaultdict(set)


# Socket connection lifecycle


async def register_connection(user_id: UUID, ws: Any) -> None:
    """Stores socket reference, loads initial user group memberships, and sets online status."""
    _local_connections[user_id] = ws

    async with get_conn() as conn:
        user_groups = await db_queries.list_user_groups(conn, user_id)

    user_group_ids = {g.group_id for g in user_groups}
    _user_groups[user_id] = user_group_ids
    for group_id in user_group_ids:
        _group_connections[group_id].add(user_id)

    await add_active_user(str(user_id))


async def unregister_connection(user_id: UUID) -> None:
    """Cleans up socket reference, removes group index, and updates active status."""
    _local_connections.pop(user_id, None)

    groups = _user_groups.pop(user_id, set())
    for group_id in groups:
        _group_connections[group_id].discard(user_id)
        if not _group_connections[group_id]:
            _group_connections.pop(group_id, None)

    await remove_active_user(str(user_id))


# Dynamic membership management for connected sockets


def on_user_joined_group(user_id: UUID, group_id: UUID) -> None:
    """Updates in-memory lookup table when a user joins a group."""
    if user_id in _local_connections:
        _group_connections[group_id].add(user_id)
        _user_groups[user_id].add(group_id)


def on_user_left_group(user_id: UUID, group_id: UUID) -> None:
    """Instantly revokes local routing when a user leaves a group."""
    _group_connections[group_id].discard(user_id)
    if user_id in _user_groups:
        _user_groups[user_id].discard(group_id)

    if not _group_connections[group_id]:
        _group_connections.pop(group_id, None)


# Internal pub/sub message listener


async def _dispatch_local_message(payload: dict[str, Any]) -> None:
    """Dispatches incoming Pub/Sub payloads to matching local direct or group connections."""
    data = payload.get("data")
    raw_user_id = payload.get("user_id")
    raw_group_id = payload.get("group_id")

    # Direct message dispatch
    if raw_user_id:
        ws = _local_connections.get(UUID(raw_user_id))
        if ws is not None:
            await ws.send_json(data)
        return

    # Group message dispatch evaluated against live local group members
    if raw_group_id:
        group_id = UUID(raw_group_id)
        sender_id = UUID(payload["sender_id"]) if payload.get("sender_id") else None

        local_members = _group_connections.get(group_id, set())
        for member_id in list(local_members):
            if member_id != sender_id:
                ws = _local_connections.get(member_id)
                if ws is not None:
                    await ws.send_json(data)


async def start_pubsub_listener() -> asyncio.Task[None]:
    """Starts background Task to listen for incoming cluster-wide pushes."""
    return asyncio.create_task(
        listen_and_dispatch_message(CHANNEL_NAME, _dispatch_local_message)
    )


# Public interface for other domain services


async def push_to_user(user_id: UUID, event: RedisEvent | dict[str, Any]) -> None:
    """Broadcasts a targeted direct payload across all server nodes."""
    data = event.to_dict() if isinstance(event, RedisEvent) else event
    payload = {"user_id": str(user_id), "data": data}
    await publish_ws_push(CHANNEL_NAME, payload)


async def push_to_group(
    group_id: UUID, event: RedisEvent | dict[str, Any], *, sender_id: UUID | None = None
) -> None:
    """Broadcasts a single group payload across all server nodes."""
    data = event.to_dict() if isinstance(event, RedisEvent) else event
    payload = {
        "group_id": str(group_id),
        "sender_id": str(sender_id) if sender_id else None,
        "data": data,
    }
    await publish_ws_push(CHANNEL_NAME, payload)


async def fetch_active_users() -> set[UUID]:
    """Returns set of active user UUIDs from Redis."""
    raw_users = await get_active_users()
    return {UUID(u) for u in raw_users}
