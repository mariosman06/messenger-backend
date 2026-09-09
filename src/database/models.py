"""Database models with automated asyncpg record conversion and field serialization."""

import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self
from uuid import UUID

import asyncpg

from src.utils.generators import uuid_v4
from src.utils.timestamps import current_ts


@dataclass
class DBModel:
    """Base dataclass providing automated mapping between asyncpg records and domain models."""

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Self:
        """Instantiates a model from an asyncpg Record, ignoring unrecognized record fields."""
        valid_keys = inspect.signature(cls.__init__).parameters.keys()
        filtered_data = {k: v for k, v in dict(record).items() if k in valid_keys}
        return cls(**filtered_data)

    @classmethod
    def from_records(cls, records: list[asyncpg.Record]) -> list[Self]:
        """Maps a list of asyncpg Record objects to a list of model instances."""
        if not records:
            return []
        return [cls.from_record(record) for record in records]

    def update_from_record(self, record: asyncpg.Record) -> Self:
        """Mutates the instance in-place with column values returned from database queries."""
        valid_keys = inspect.signature(self.__init__).parameters.keys()
        for k, v in dict(record).items():
            if k in valid_keys:
                setattr(self, k, v)
        return self

    def to_args(self) -> tuple[Any, ...]:
        """Extracts dataclass field values with subclass fields first,

        followed by base DBModel fields (created_at, updated_at, etc.).
        """
        ordered_fields: list[str] = []

        for cls in self.__class__.__mro__:
            if hasattr(cls, "__annotations__") and cls is not object:
                for field_name in cls.__annotations__:
                    if field_name not in ordered_fields and hasattr(self, field_name):
                        ordered_fields.append(field_name)

        return tuple(getattr(self, name) for name in ordered_fields)


# User


@dataclass(kw_only=True)
class User(DBModel):
    """Database model representing a registered application user account."""

    user_id: UUID = field(default_factory=uuid_v4)
    username: str
    password_hash: str
    deactivated: bool = False
    created_at: datetime = field(default_factory=current_ts)


# Friendship


@dataclass(kw_only=True)
class Friendship(DBModel):
    """Database model representing a friend connection or pending request between users."""

    requester_id: UUID
    addressee_id: UUID
    accepted: bool = False
    created_at: datetime = field(default_factory=current_ts)
    updated_at: datetime = field(default_factory=current_ts)


# Token


@dataclass(kw_only=True)
class AccessToken(DBModel):
    """Database model representing an API authentication access token."""

    token_hash: str
    user_id: UUID
    is_revoked: bool = False
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        """Determines whether the access token has exceeded its expiration timestamp."""
        return current_ts() >= self.expires_at


@dataclass(kw_only=True)
class RefreshToken(DBModel):
    """Database model representing a session renewal refresh token."""

    token_hash: str
    user_id: UUID
    is_revoked: bool = False
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        """Determines whether the refresh token has exceeded its expiration timestamp."""
        return current_ts() >= self.expires_at


# Group


@dataclass(kw_only=True)
class Group(DBModel):
    """Database model representing a group chat entity."""

    group_id: UUID = field(default_factory=uuid_v4)
    name: str
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=current_ts)


# Membership


@dataclass(kw_only=True)
class Membership(DBModel):
    """Database model representing a user's association with a specific group."""

    group_id: UUID
    user_id: UUID
    joined_at: datetime = field(default_factory=current_ts)

    @property
    def pk(self) -> tuple[UUID, UUID]:
        return self.group_id, self.user_id


# Message


@dataclass(kw_only=True)
class DirectMessage(DBModel):
    """Database model representing a point-to-point direct message between two users."""

    message_id: UUID = field(default_factory=uuid_v4)
    sender_id: UUID
    recipient_id: UUID
    content: str
    created_at: datetime = field(default_factory=current_ts)


@dataclass(kw_only=True)
class GroupMessage(DBModel):
    """Database model representing a message broadcast within a group context."""

    message_id: UUID = field(default_factory=uuid_v4)
    group_id: UUID
    sender_id: UUID
    content: str
    created_at: datetime = field(default_factory=current_ts)
