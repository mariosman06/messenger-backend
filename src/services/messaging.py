"""Messaging service managing Direct Messages and timeline history retrieval."""

import logging
from datetime import UTC, datetime
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import DatabaseManager
from src.database.enums import Entity as DBEntity
from src.database.models import DirectMessage, GroupMessage
from src.redis.events import DirectMessageEvent, GroupMessageEvent
from src.services.websocket import WebSocketManager
from src.utils.tasks import spawn_task

from .errors import (
    DirectMessageNotAllowedError,
    GroupMessageNotAllowedError,
    handle_db_constraint_error,
    handle_db_not_found_error,
)

logger = logging.getLogger(__name__)


class MessagingService:
    """Coordinates direct and group messaging writes and real-time fanout."""

    def __init__(self, db: DatabaseManager, ws_manager: WebSocketManager) -> None:
        self._db = db
        self._ws = ws_manager

    @handle_db_constraint_error()
    @handle_db_not_found_error(
        overrides={
            DBEntity.FRIENDSHIP: lambda **kw: DirectMessageNotAllowedError(kw["recipient_id"]),
        }
    )
    async def send_direct_message(
        self, *, sender_id: UUID, recipient_id: UUID, content: str
    ) -> DirectMessage:
        """Persists a direct message and dispatches WebSocket notification across cluster nodes."""
        async with self._db.transaction() as conn:
            friendship = await db_queries.get_friendship_status(conn, sender_id, recipient_id)
            if not friendship.accepted:
                logger.warning(
                    "User %s attempted to DM user %s without accepted friendship.",
                    sender_id,
                    recipient_id,
                )
                raise DirectMessageNotAllowedError(recipient_id)

            message = DirectMessage(
                sender_id=sender_id, recipient_id=recipient_id, content=content
            )
            dm = await db_queries.send_direct_message(conn, message)
            logger.info(
                "Direct message %s sent from %s to %s.", dm.message_id, sender_id, recipient_id
            )

        spawn_task(
            self._ws.push_to_user(
                recipient_id,
                DirectMessageEvent.from_model(dm),
            )
        )
        return dm

    @handle_db_constraint_error()
    @handle_db_not_found_error(
        overrides={
            DBEntity.FRIENDSHIP: lambda **kw: DirectMessageNotAllowedError(kw["recipient_id"]),
        }
    )
    async def get_dm_history(
        self,
        *,
        actor_id: UUID,
        recipient_id: UUID,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[DirectMessage]:
        """Retrieves paginated DM conversation history between two verified friends."""
        cutoff = before or datetime.now(UTC)

        async with self._db.connection() as conn:
            friendship = await db_queries.get_friendship_status(conn, actor_id, recipient_id)
            if not friendship.accepted:
                logger.warning(
                    "User %s attempted to read DM history with %s without friendship.",
                    actor_id,
                    recipient_id,
                )
                raise DirectMessageNotAllowedError(recipient_id)

            return await db_queries.get_dm_conversation_history(
                conn, actor_id, recipient_id, cutoff, limit
            )

    @handle_db_constraint_error()
    @handle_db_not_found_error(
        overrides={
            DBEntity.MEMBERSHIP: lambda **kw: GroupMessageNotAllowedError(kw["group_id"]),
        }
    )
    async def send_group_message(
        self, *, sender_id: UUID, group_id: UUID, content: str
    ) -> GroupMessage:
        """Persists a group message and broadcasts to local members of other worker nodes."""
        async with self._db.transaction() as conn:
            await db_queries.get_membership(conn, group_id, sender_id)

            message = GroupMessage(group_id=group_id, sender_id=sender_id, content=content)
            msg = await db_queries.send_group_message(conn, message)

            logger.info(
                "Group message %s sent to group %s by user %s.",
                msg.message_id,
                group_id,
                sender_id,
            )

        spawn_task(
            self._ws.push_to_group(
                group_id,
                GroupMessageEvent.from_model(msg),
                sender_id=sender_id,
            )
        )
        return msg

    @handle_db_constraint_error()
    @handle_db_not_found_error(
        overrides={
            DBEntity.MEMBERSHIP: lambda **kw: GroupMessageNotAllowedError(kw["group_id"]),
        }
    )
    async def get_group_history(
        self,
        *,
        actor_id: UUID,
        group_id: UUID,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[GroupMessage]:
        """Retrieves group messaging history after verifying caller membership."""
        cutoff = before or datetime.now(UTC)

        async with self._db.connection() as conn:
            await db_queries.get_membership(conn, group_id, actor_id)
            return await db_queries.get_group_messages_timeline(conn, group_id, cutoff, limit)
