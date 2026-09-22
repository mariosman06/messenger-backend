import asyncio
import logging
import weakref
from collections import defaultdict
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

import src.database.queries as db_queries
from src.database.connection import DatabaseManager
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


class WebSocketManager:
    """Manages worker-local WebSocket registries, lifecycle locks, and cluster Pub/Sub fanout."""

    def __init__(
        self,
        db: DatabaseManager,
        redis: Redis,
        redis_url: str | None = None,
        channel_name: str = CHANNEL_NAME,
    ) -> None:
        self._db = db
        self._redis = redis
        self._redis_url = redis_url
        self._channel_name = channel_name

        # Worker-local memory routing registries
        self._local_connections: dict[UUID, set[Any]] = defaultdict(set)
        self._group_connections: dict[UUID, set[UUID]] = defaultdict(set)
        self._user_groups: dict[UUID, set[UUID]] = defaultdict(set)

        # Lock dictionary using weak references for automatic, race-condition-free GC
        self._user_locks: weakref.WeakValueDictionary[UUID, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def _get_user_lock(self, user_id: UUID) -> asyncio.Lock:
        """Retrieves or creates an asyncio.Lock for a given user, cleaned up automatically when idle."""
        lock = self._user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._user_locks[user_id] = lock
        return lock

    async def register_connection(self, user_id: UUID, ws: Any) -> None:
        """Registers a socket instance and merges initial group memberships safely with DB pool timeout protection."""
        self._local_connections[user_id].add(ws)

        await add_active_user(self._redis, str(user_id))

        user_group_ids: set[UUID] = set()
        try:
            async with asyncio.timeout(5.0):
                async with self._db.connection() as conn:
                    user_groups = await db_queries.list_user_groups(conn, user_id=user_id)
                user_group_ids = {g.group_id for g in user_groups}
        except TimeoutError:
            logger.warning("DB query timed out during WS registration for user %s", user_id)
        except Exception as exc:
            logger.error(
                "Failed to load user groups for %s during WS connect: %s", user_id, exc
            )

        # Only populate group state if socket wasn't disconnected during the DB query yield
        if user_id in self._local_connections and ws in self._local_connections[user_id]:
            self._user_groups[user_id].update(user_group_ids)
            for group_id in user_group_ids:
                self._group_connections[group_id].add(user_id)

    async def unregister_connection(self, user_id: UUID, ws: Any) -> None:
        """Removes a socket instance and evicts in-memory routing only when the final session closes."""
        async with self._get_user_lock(user_id):
            sockets = self._local_connections.get(user_id)
            if sockets:
                sockets.discard(ws)

            # Only wipe routing state and notify Redis if the user has NO remaining active sockets
            if not self._local_connections.get(user_id):
                self._local_connections.pop(user_id, None)
                groups = self._user_groups.pop(user_id, set())
                for group_id in groups:
                    self._group_connections[group_id].discard(user_id)
                    if not self._group_connections[group_id]:
                        self._group_connections.pop(group_id, None)

                await remove_active_user(self._redis, str(user_id))

    async def push_group_membership_change(
        self, user_id: UUID, group_id: UUID, action: MembershipAction | str
    ) -> None:
        """Broadcasts membership changes across all workers via Redis Pub/Sub."""
        act = MembershipAction(action) if isinstance(action, str) else action
        event = GroupMembershipEvent(user_id=user_id, group_id=group_id, action=act)
        await publish_ws_push(self._redis, self._channel_name, {"data": event.to_dict()})

    async def push_group_deleted(self, group_id: UUID) -> None:
        """Broadcasts group deletion across all server nodes via Pub/Sub."""
        event = GroupDeletedEvent(group_id=group_id)
        await publish_ws_push(self._redis, self._channel_name, {"data": event.to_dict()})

    async def push_to_user(self, user_id: UUID, event: RedisEvent | dict[str, Any]) -> None:
        """Broadcasts a targeted direct payload across all server nodes via Pub/Sub."""
        data = event.to_dict() if isinstance(event, RedisEvent) else event
        payload = {"user_id": str(user_id), "data": data}
        await publish_ws_push(self._redis, self._channel_name, payload)

    async def push_to_group(
        self,
        group_id: UUID,
        event: RedisEvent | dict[str, Any],
        *,
        sender_id: UUID | None = None,
    ) -> None:
        """Broadcasts a group payload across all server nodes via Pub/Sub."""
        data = event.to_dict() if isinstance(event, RedisEvent) else event
        payload = {
            "group_id": str(group_id),
            "sender_id": str(sender_id) if sender_id else None,
            "data": data,
        }
        await publish_ws_push(self._redis, self._channel_name, payload)

    async def _send_frame_to_user_sockets(
        self, user_id: UUID, payload_data: dict[str, Any]
    ) -> None:
        """Concurrently broadcasts a JSON frame using zero-overhead asyncio.timeout context managers."""
        sockets = list(self._local_connections.get(user_id, set()))
        if not sockets:
            return

        async def _safe_send(ws: Any) -> None:
            try:
                async with asyncio.timeout(1.0):
                    await ws.send_json(payload_data)
            except Exception as exc:
                logger.warning(
                    "Failed or timed out sending WS frame to user %s: %s", user_id, exc
                )

        await asyncio.gather(*[_safe_send(ws) for ws in sockets])

    async def _handle_membership_change(self, data: dict[str, Any]) -> None:
        """Synchronizes cluster-wide membership state and notifies connected client sockets."""
        user_id = UUID(data["user_id"])
        group_id = UUID(data["group_id"])
        action = MembershipAction(data["action"])

        if action == MembershipAction.JOIN:
            if user_id in self._local_connections:
                self._group_connections[group_id].add(user_id)
                self._user_groups[user_id].add(group_id)

        elif action == MembershipAction.LEAVE:
            self._group_connections[group_id].discard(user_id)
            if user_id in self._user_groups:
                self._user_groups[user_id].discard(group_id)
            if not self._group_connections[group_id]:
                self._group_connections.pop(group_id, None)

        await self._send_frame_to_user_sockets(user_id, data)

    async def _handle_group_deleted(self, data: dict[str, Any]) -> None:
        """Synchronizes cluster-wide deletion state and notifies local members."""
        group_id = UUID(data["group_id"])
        local_members = list(self._group_connections.get(group_id, set()))

        if local_members:
            await asyncio.gather(
                *[self._send_frame_to_user_sockets(m_id, data) for m_id in local_members]
            )

        for member_id in local_members:
            if member_id in self._user_groups:
                self._user_groups[member_id].discard(group_id)
        self._group_connections.pop(group_id, None)

    async def _dispatch_direct_message(self, raw_user_id: str, data: dict[str, Any]) -> None:
        """Delivers targeted direct messages to active local sockets."""
        await self._send_frame_to_user_sockets(UUID(raw_user_id), data)

    async def _dispatch_group_message(self, payload: dict[str, Any]) -> None:
        """Concurrently broadcasts group payloads to local members, excluding sender."""
        group_id = UUID(payload["group_id"])
        sender_id = UUID(payload["sender_id"]) if payload.get("sender_id") else None
        data: dict[str, Any] = payload.get("data") or {}

        local_members = [
            member_id
            for member_id in self._group_connections.get(group_id, set())
            if member_id != sender_id
        ]

        if local_members:
            await asyncio.gather(
                *[self._send_frame_to_user_sockets(m_id, data) for m_id in local_members]
            )

    async def _dispatch_local_message(self, payload: dict[str, Any]) -> None:
        """Dispatches incoming Pub/Sub payloads based on event type and routing hints."""
        data = payload.get("data", {})
        event_type = data.get("event")

        if event_type == EventType.GROUP_MEMBERSHIP:
            await self._handle_membership_change(data)
            return

        if event_type == EventType.GROUP_DELETED:
            await self._handle_group_deleted(data)
            return

        if raw_user_id := payload.get("user_id"):
            await self._dispatch_direct_message(raw_user_id, data)
            return

        if payload.get("group_id"):
            await self._dispatch_group_message(payload)
            return

    def start_pubsub_listener(self) -> asyncio.Task[None]:
        """Starts a background worker listening for cluster Pub/Sub pushes."""
        if self._redis_url:
            pubsub_redis = Redis.from_url(self._redis_url, decode_responses=True)
            close_client = True
        else:
            pubsub_redis = self._redis
            close_client = False

        return asyncio.create_task(
            listen_and_dispatch_message(
                pubsub_redis,
                self._channel_name,
                self._dispatch_local_message,
                close_client_on_exit=close_client,
            )
        )

    async def fetch_active_users(self) -> set[UUID]:
        """Returns the set of active user UUIDs currently tracked in Redis."""
        raw_users = await get_active_users(self._redis)
        return {UUID(u) for u in raw_users}
