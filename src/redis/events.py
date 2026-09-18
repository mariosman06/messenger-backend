"""Redis event models for WebSocket payloads and System Streams."""

from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.database.models import DirectMessage, GroupMessage


class EventType(StrEnum):
    # WebSocket Client Events
    DIRECT_MESSAGE = "direct_message"
    GROUP_MESSAGE = "group_message"
    GROUP_MEMBERSHIP = "group_membership"
    GROUP_DELETED = "group_deleted"

    # System Cache Invalidation Events
    USER_INVALIDATED = "user_invalidated"
    TOKEN_REVOKED = "token_revoked"


class MembershipAction(StrEnum):
    JOIN = "JOIN"
    LEAVE = "LEAVE"


@dataclass(kw_only=True)
class RedisEvent:
    """Base model for Redis events with automated serialization."""

    event: EventType

    def to_dict(self) -> dict[str, Any]:
        """Converts event attributes to a JSON-compatible dictionary."""
        data: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, UUID):
                data[f.name] = str(val)
            elif isinstance(val, datetime):
                data[f.name] = val.isoformat()
            elif isinstance(val, StrEnum):
                data[f.name] = val.value
            else:
                data[f.name] = val
        return data


# WebSocket Client Events


@dataclass(kw_only=True)
class DirectMessageEvent(RedisEvent):
    """Event payload broadcast when a direct message is sent."""

    event: EventType = EventType.DIRECT_MESSAGE
    message_id: UUID
    sender_id: UUID
    recipient_id: UUID
    content: str
    created_at: datetime

    @classmethod
    def from_model(cls, dm: DirectMessage) -> "DirectMessageEvent":
        return cls(
            message_id=dm.message_id,
            sender_id=dm.sender_id,
            recipient_id=dm.recipient_id,
            content=dm.content,
            created_at=dm.created_at,
        )


@dataclass(kw_only=True)
class GroupMessageEvent(RedisEvent):
    """Event payload broadcast when a group message is sent."""

    event: EventType = EventType.GROUP_MESSAGE
    message_id: UUID
    group_id: UUID
    sender_id: UUID
    content: str
    created_at: datetime

    @classmethod
    def from_model(cls, msg: GroupMessage) -> "GroupMessageEvent":
        return cls(
            message_id=msg.message_id,
            group_id=msg.group_id,
            sender_id=msg.sender_id,
            content=msg.content,
            created_at=msg.created_at,
        )


@dataclass(kw_only=True)
class GroupMembershipEvent(RedisEvent):
    """Event payload broadcast when a user joins or leaves a group."""

    event: EventType = EventType.GROUP_MEMBERSHIP
    action: MembershipAction
    user_id: UUID
    group_id: UUID


@dataclass(kw_only=True)
class GroupDeletedEvent(RedisEvent):
    """Event payload broadcast when a group is deleted."""

    event: EventType = EventType.GROUP_DELETED
    group_id: UUID


# System Invalidation Events


@dataclass(kw_only=True)
class UserInvalidatedEvent(RedisEvent):
    """Broadcast when a user password changes, account is deactivated, or global logout occurs."""

    event: EventType = EventType.USER_INVALIDATED
    user_id: UUID


@dataclass(kw_only=True)
class TokenRevokedEvent(RedisEvent):
    """Broadcast when a specific token is logged out or rotated."""

    event: EventType = EventType.TOKEN_REVOKED
    token_hash: str
