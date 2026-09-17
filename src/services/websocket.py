"""Manages local WebSocket connections, Redis user tracking, and Pub/Sub delivery."""

import asyncio
import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import get_conn
from src.redis.events import (
    EventType,
    GroupDeletedEvent,
    GroupMembershipEvent,
    MembershipAction,
    RedisEvent,
)
from src.redis.pubsub import listen_and_dispatch_message, publish_ws_push
from src.redis.queries import add_active_user, get_active_users, remove_active_user

logger = logging.getLogger(__name__)

CHANNEL_NAME = "ws_pushes"

_local_connections: dict[UUID, set[Any]] = defaultdict(set)
_group_connections: dict[UUID, set[UUID]] = defaultdict(set)
_user_groups: dict[UUID, set[UUID]] = defaultdict(set)
_user_locks: dict[UUID, asyncio.Lock] = {}


def _get_user_lock(user_id: UUID) -> asyncio.Lock:
    """Returns or creates a per-user lock to serialize connection lifecycle events."""
    return _user_locks.setdefault(user_id, asyncio.Lock())


async def register_connection(user_id: UUID, ws: Any) -> None:
    """Registers a socket instance and merges initial group memberships safely."""
    async with _get_user_lock(user_id):
        _local_connections[user_id].add(ws)

    await add_active_user(str(user_id))

    try:
        async with get_conn() as conn:
            user_groups = await db_queries.list_user_groups(conn, user_id=user_id)
        user_group_ids = {g.group_id for g in user_groups}
    except Exception as exc:
        logger.error("Failed to load user groups for %s during WS connect: %s", user_id, exc)
        user_group_ids = set()

    async with _get_user_lock(user_id):
        # Only populate group state if the socket wasn't disconnected during the DB query
        if user_id in _local_connections and ws in _local_connections[user_id]:
            _user_groups[user_id].update(user_group_ids)
            for group_id in user_group_ids:
                _group_connections[group_id].add(user_id)


async def unregister_connection(user_id: UUID, ws: Any) -> None:
    """Removes a socket instance and cleans up in-memory routing when the last socket closes."""
    async with _get_user_lock(user_id):
        sockets = _local_connections.get(user_id)
        if sockets:
            sockets.discard(ws)

        if not _local_connections.get(user_id):
            _local_connections.pop(user_id, None)
            groups = _user_groups.pop(user_id, set())
            for group_id in groups:
                _group_connections[group_id].discard(user_id)
                if not _group_connections[group_id]:
                    _group_connections.pop(group_id, None)

            await remove_active_user(str(user_id))


async def push_group_membership_change(
    user_id: UUID, group_id: UUID, action: MembershipAction | str
) -> None:
    """Broadcasts membership changes across all workers via Redis Pub/Sub."""
    act = MembershipAction(action) if isinstance(action, str) else action
    event = GroupMembershipEvent(user_id=user_id, group_id=group_id, action=act)
    await publish_ws_push(CHANNEL_NAME, {"data": event.to_dict()})


async def push_group_deleted(group_id: UUID) -> None:
    """Broadcasts group deletion across all server nodes via Pub/Sub."""
    event = GroupDeletedEvent(group_id=group_id)
    await publish_ws_push(CHANNEL_NAME, {"data": event.to_dict()})


async def push_to_user(user_id: UUID, event: RedisEvent | dict[str, Any]) -> None:
    """Broadcasts a targeted direct payload across all server nodes via Pub/Sub."""
    data = event.to_dict() if isinstance(event, RedisEvent) else event
    payload = {"user_id": str(user_id), "data": data}
    await publish_ws_push(CHANNEL_NAME, payload)


async def push_to_group(
    group_id: UUID, event: RedisEvent | dict[str, Any], *, sender_id: UUID | None = None
) -> None:
    """Broadcasts a group payload across all server nodes via Pub/Sub."""
    data = event.to_dict() if isinstance(event, RedisEvent) else event
    payload = {
        "group_id": str(group_id),
        "sender_id": str(sender_id) if sender_id else None,
        "data": data,
    }
    await publish_ws_push(CHANNEL_NAME, payload)


async def _send_frame_to_user_sockets(user_id: UUID, payload_data: dict[str, Any]) -> None:
    """Concurrently broadcasts a JSON frame with a 2-second timeout to prevent blocked loops."""
    sockets = list(_local_connections.get(user_id, set()))
    if not sockets:
        return

    async def _safe_send(ws: Any) -> None:
        try:
            await asyncio.wait_for(ws.send_json(payload_data), timeout=2.0)
        except Exception as exc:
            logger.warning("Failed or timed out sending WS frame to user %s: %s", user_id, exc)

    await asyncio.gather(*[_safe_send(ws) for ws in sockets])


async def _handle_membership_change(data: dict[str, Any]) -> None:
    """Synchronizes cluster-wide membership state and notifies connected client sockets."""
    user_id = UUID(data["user_id"])
    group_id = UUID(data["group_id"])
    action = MembershipAction(data["action"])

    async with _get_user_lock(user_id):
        if action == MembershipAction.JOIN:
            if user_id in _local_connections:
                _group_connections[group_id].add(user_id)
                _user_groups[user_id].add(group_id)

        elif action == MembershipAction.LEAVE:
            _group_connections[group_id].discard(user_id)
            if user_id in _user_groups:
                _user_groups[user_id].discard(group_id)
            if not _group_connections[group_id]:
                _group_connections.pop(group_id, None)

    # Deliver frame outside the lock to prevent network blocking
    await _send_frame_to_user_sockets(user_id, data)


async def _handle_group_deleted(data: dict[str, Any]) -> None:
    """Synchronizes cluster-wide deletion state and notifies local members."""
    group_id = UUID(data["group_id"])
    local_members = list(_group_connections.get(group_id, set()))

    if local_members:
        await asyncio.gather(
            *[_send_frame_to_user_sockets(m_id, data) for m_id in local_members]
        )

    for member_id in local_members:
        async with _get_user_lock(member_id):
            if member_id in _user_groups:
                _user_groups[member_id].discard(group_id)
    _group_connections.pop(group_id, None)


async def _dispatch_direct_message(raw_user_id: str, data: dict[str, Any]) -> None:
    """Delivers targeted direct messages to all active local sockets for a user."""
    await _send_frame_to_user_sockets(UUID(raw_user_id), data)


async def _dispatch_group_message(payload: dict[str, Any]) -> None:
    """Concurrently broadcasts group payloads to local members, excluding the sender."""
    group_id = UUID(payload["group_id"])
    sender_id = UUID(payload["sender_id"]) if payload.get("sender_id") else None
    data: dict[str, Any] = payload.get("data") or {}

    local_members = [
        member_id
        for member_id in _group_connections.get(group_id, set())
        if member_id != sender_id
    ]

    if local_members:
        await asyncio.gather(
            *[_send_frame_to_user_sockets(m_id, data) for m_id in local_members]
        )


async def _dispatch_local_message(payload: dict[str, Any]) -> None:
    """Dispatches incoming Pub/Sub payloads based on event type and routing hints."""
    data = payload.get("data", {})
    event_type = data.get("event")

    if event_type == EventType.GROUP_MEMBERSHIP:
        await _handle_membership_change(data)
        return

    if event_type == EventType.GROUP_DELETED:
        await _handle_group_deleted(data)
        return

    if raw_user_id := payload.get("user_id"):
        await _dispatch_direct_message(raw_user_id, data)
        return

    if payload.get("group_id"):
        await _dispatch_group_message(payload)
        return


def start_pubsub_listener() -> asyncio.Task[None]:
    """Starts a strongly-referenced background task to listen for cluster-wide Pub/Sub pushes."""
    return asyncio.create_task(
        listen_and_dispatch_message(CHANNEL_NAME, _dispatch_local_message)
    )


async def fetch_active_users() -> set[UUID]:
    """Returns the set of active user UUIDs currently tracked in Redis."""
    raw_users = await get_active_users()
    return {UUID(u) for u in raw_users}
