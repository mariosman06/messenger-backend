"""Messaging service CRUD DM and group chat operations."""

import logging
from datetime import UTC, datetime
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import get_conn, get_transaction
from src.database.enums import Entity as DBEntity
from src.database.models import DirectMessage, GroupMessage

from .errors import (
    DirectMessageNotAllowedError,
    GroupMessageNotAllowedError,
    handle_db_constraint_error,
    handle_db_not_found_error,
)

logger = logging.getLogger(__name__)


@handle_db_constraint_error()
@handle_db_not_found_error(
    overrides={
        DBEntity.FRIENDSHIP: lambda **kw: DirectMessageNotAllowedError(kw["recipient_id"]),
    }
)
async def send_direct_message(
    *, sender_id: UUID, recipient_id: UUID, content: str
) -> DirectMessage:
    """Sends a direct message after verifying an accepted friendship."""
    async with get_transaction() as conn:
        friendship = await db_queries.get_friendship_status(conn, sender_id, recipient_id)
        if not friendship.accepted:
            logger.warning(
                "User %s attempted to DM user %s without an accepted friendship.",
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
        return dm


@handle_db_constraint_error()
@handle_db_not_found_error(
    overrides={
        DBEntity.FRIENDSHIP: lambda **kw: DirectMessageNotAllowedError(kw["recipient_id"]),
    }
)
async def get_dm_history(
    *,
    actor_id: UUID,
    recipient_id: UUID,
    before: datetime | None = None,
    limit: int = 50,
) -> list[DirectMessage]:
    """Retrieves DM conversation history between two accepted friends."""
    cutoff = before or datetime.now(UTC)

    async with get_conn() as conn:
        friendship = await db_queries.get_friendship_status(conn, actor_id, recipient_id)
        if not friendship.accepted:
            logger.warning(
                "User %s attempted to read DM history with user %s without an accepted friendship.",
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
async def send_group_message(*, sender_id: UUID, group_id: UUID, content: str) -> GroupMessage:
    """Sends a message to a group after verifying caller membership."""
    async with get_transaction() as conn:
        await db_queries.get_membership(conn, group_id, sender_id)

        message = GroupMessage(group_id=group_id, sender_id=sender_id, content=content)
        msg = await db_queries.send_group_message(conn, message)
        logger.info(
            "Group message %s sent to group %s by user %s.",
            msg.message_id,
            group_id,
            sender_id,
        )
        return msg


@handle_db_constraint_error()
@handle_db_not_found_error(
    overrides={
        DBEntity.MEMBERSHIP: lambda **kw: GroupMessageNotAllowedError(kw["group_id"]),
    }
)
async def get_group_history(
    *,
    actor_id: UUID,
    group_id: UUID,
    before: datetime | None = None,
    limit: int = 50,
) -> list[GroupMessage]:
    """Retrieves group messaging timeline after verifying caller membership."""
    cutoff = before or datetime.now(UTC)

    async with get_conn() as conn:
        await db_queries.get_membership(conn, group_id, actor_id)

        return await db_queries.get_group_messages_timeline(conn, group_id, cutoff, limit)
