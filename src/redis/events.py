"""Redis event models for WebSocket payloads."""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any
from uuid import UUID

from src.database.models import DirectMessage, GroupMessage


@dataclass(kw_only=True)
class RedisEvent:
    """Base model for Redis Pub/Sub events with automated serialization."""

    event: str

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

    event: str = "direct_message"
    message_id: UUID
    sender_id: UUID
    recipient_id: UUID
    content: str
    created_at: datetime

    @classmethod
    def from_model(cls, dm: DirectMessage) -> "DirectMessageEvent":
        """Constructs an event instance directly from a DirectMessage DB model."""
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

    event: str = "group_message"
    message_id: UUID
    group_id: UUID
    sender_id: UUID
    content: str
    created_at: datetime

    @classmethod
    def from_model(cls, msg: GroupMessage) -> "GroupMessageEvent":
        """Constructs an event instance directly from a GroupMessage DB model."""
        return cls(
            message_id=msg.message_id,
            group_id=msg.group_id,
            sender_id=msg.sender_id,
            content=msg.content,
            created_at=msg.created_at,
        )
