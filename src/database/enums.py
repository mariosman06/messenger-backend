"""StrEnums for schema entities, SQL transaction levels, constraints, and indexes."""

from enum import StrEnum, auto


class Entity(StrEnum):
    """Explicit names for database table entities."""

    # User
    USER = auto()

    # Token
    ACCESS_TOKEN = auto()
    REFRESH_TOKEN = auto()

    # Friendship
    FRIENDSHIP = auto()

    # Group
    GROUP = auto()

    # Membership
    MEMBERSHIP = auto()

    # Messages
    DIRECT_MESSAGE = auto()
    GROUP_MESSAGE = auto()


class CommandStatus(StrEnum):
    """PostgreSQL command completion tags for zero-row mutation checks."""

    UPDATE_ZERO = "UPDATE 0"
    DELETE_ZERO = "DELETE 0"


class IsolationLevel(StrEnum):
    """SQL transaction isolation levels for database operations."""

    READ_COMMITTED = auto()
    REPEATABLE_READ = auto()
    SERIALIZABLE = auto()


class Constraint(StrEnum):
    """Explicit names for database primary keys, foreign keys, and unique constraints."""

    # User
    PK_USERS = auto()
    UQ_USERS_USERNAME = auto()

    # Friendship
    PK_FRIENDSHIPS = auto()
    FK_FRIENDSHIPS_REQUESTER_ID = auto()
    FK_FRIENDSHIPS_ADDRESSEE_ID = auto()

    # Token
    PK_ACCESS_TOKENS = auto()
    FK_ACCESS_TOKENS_USER_ID = auto()
    PK_REFRESH_TOKENS = auto()
    FK_REFRESH_TOKENS_USER_ID = auto()

    # Group
    PK_GROUPS = auto()
    UQ_GROUPS_CREATED_BY_NAME = "uq_groups_created_by_name"
    FK_GROUPS_CREATED_BY = auto()

    # Membership
    PK_MEMBERSHIPS = auto()
    FK_MEMBERSHIPS_GROUP_ID = auto()
    FK_MEMBERSHIPS_USER_ID = auto()

    # Messages
    PK_DIRECT_MESSAGES = auto()
    FK_DM_SENDER_ID = auto()
    FK_DM_RECIPIENT_ID = auto()
    PK_GROUP_MESSAGES = auto()
    FK_GROUP_MESSAGES_GROUP_ID = auto()
    FK_GROUP_MESSAGES_SENDER_ID = auto()


class Index(StrEnum):
    """Explicit names for database indexes used across application queries."""

    # Friendship
    IDX_FRIENDSHIPS_ADDRESSEE_ID = auto()

    # Token
    IDX_ACCESS_TOKENS_USER_ID = auto()
    IDX_REFRESH_TOKENS_USER_ID = auto()
    IDX_ACCESS_TOKENS_EXPIRES_AT = auto()
    IDX_REFRESH_TOKENS_EXPIRES_AT = auto()

    # Group
    IDX_GROUPS_CREATED_BY = auto()

    # Membership
    IDX_MEMBERSHIPS_USER_ID = auto()

    # Messages
    IDX_DM_SENDER_RECIPIENT = auto()
    IDX_DM_RECIPIENT_SENDER = auto()
    IDX_GROUP_MESSAGES_TIMELINE = auto()
    IDX_GROUP_MESSAGES_SENDER_ID = auto()
