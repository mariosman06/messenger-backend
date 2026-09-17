"""Redis event models for WebSocket payloads."""

from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from src.database.models import DirectMessage, GroupMessage


class EventType(StrEnum):
    DIRECT_MESSAGE = "direct_message"
    GROUP_MESSAGE = "group_message"
    GROUP_MEMBERSHIP = "group_membership"
    GROUP_DELETED = "group_deleted"


class MembershipAction(StrEnum):
    JOIN = "JOIN"
    LEAVE = "LEAVE"


@dataclass(kw_only=True)
class RedisEvent:
    """Base model for Redis Pub/Sub events with automated serialization."""

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
            else:
                data[f.name] = val
        return data


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
