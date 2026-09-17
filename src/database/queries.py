"""Database repository executing query operations and schema management."""

from datetime import datetime
from uuid import UUID

import asyncpg

from .enums import CommandStatus, Entity
from .errors import ConstraintViolationError, NotFoundError
from .models import (
    AccessToken,
    DirectMessage,
    Friendship,
    Group,
    GroupMessage,
    Membership,
    RefreshToken,
    User,
)
from .sql import CLEAR_TABLES, Delete, EnsureIndexExists, EnsureTableExists, Fetch, Write

# Schema Setup


async def ensure_tables_exist(conn: asyncpg.Connection) -> None:
    """Executes table creation DDL statements."""
    for statement in EnsureTableExists:
        await conn.execute(statement)


async def ensure_indexes_exist(conn: asyncpg.Connection) -> None:
    """Executes index creation DDL statements."""
    for statement in EnsureIndexExists:
        await conn.execute(statement)


# Clear tables


async def clear_tables(conn: asyncpg.Connection) -> None:
    await conn.execute(CLEAR_TABLES)


# Query Locking Helper


def _with_lock(query: str, for_update: bool) -> str:
    """Appends FOR UPDATE row-level lock clause to a query string when requested."""
    if not for_update:
        return query
    return f"{query.rstrip().rstrip(';')} FOR UPDATE;"


# User Operations


async def get_user_by_id(
    conn: asyncpg.Connection, user_id: UUID, *, for_update: bool = False
) -> User:
    """Retrieves a user by unique identifier."""
    query = _with_lock(Fetch.USER_BY_ID, for_update)
    record = await conn.fetchrow(query, user_id)
    if not record:
        raise NotFoundError(entity=Entity.USER, identifier=str(user_id))
    return User.from_record(record)


async def get_user_by_username(
    conn: asyncpg.Connection, username: str, *, for_update: bool = False
) -> User:
    """Retrieves a user by unique username."""
    query = _with_lock(Fetch.USER_BY_USERNAME, for_update)
    record = await conn.fetchrow(query, username)
    if not record:
        raise NotFoundError(entity=Entity.USER, identifier=username)
    return User.from_record(record)


async def create_user(conn: asyncpg.Connection, user: User) -> User:
    """Persists a new user record into the database."""
    try:
        record = await conn.fetchrow(Write.INSERT_USER, *user.to_args())
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e

    if not record:
        raise NotFoundError(entity=Entity.USER, identifier=str(user.user_id))
    return user.update_from_record(record)


async def deactivate_user(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Flags a user account as deactivated."""
    status = await conn.execute(Write.DEACTIVATE_USER, user_id)
    if status == CommandStatus.UPDATE_ZERO:
        raise NotFoundError(entity=Entity.USER, identifier=str(user_id))


async def reactivate_user(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Reactivates a previously deactivated user account."""
    status = await conn.execute(Write.REACTIVATE_USER, user_id)
    if status == CommandStatus.UPDATE_ZERO:
        raise NotFoundError(entity=Entity.USER, identifier=str(user_id))


async def update_user_password(
    conn: asyncpg.Connection,
    user_id: UUID,
    new_password_hash: str,
    old_password_hash: str,
) -> None:
    """Updates a user's password hash matching the previous hash."""
    status = await conn.execute(
        Write.CHANGE_PASSWORD, new_password_hash, user_id, old_password_hash
    )
    if status == CommandStatus.UPDATE_ZERO:
        raise NotFoundError(entity=Entity.USER, identifier=str(user_id))


async def delete_user(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Hard-deletes a user account record."""
    status = await conn.execute(Delete.USER_BY_ID, user_id)
    if status == CommandStatus.DELETE_ZERO:
        raise NotFoundError(entity=Entity.USER, identifier=str(user_id))


# Friendship Operations


async def get_friendship_status(
    conn: asyncpg.Connection,
    user_a: UUID,
    user_b: UUID,
    *,
    for_update: bool = False,
) -> Friendship:
    """Fetches relationship status between two users."""
    query = _with_lock(Fetch.FRIENDSHIP_STATUS, for_update)
    record = await conn.fetchrow(query, user_a, user_b)
    if not record:
        raise NotFoundError(entity=Entity.FRIENDSHIP, identifier=f"{user_a} <-> {user_b}")
    return Friendship.from_record(record)


async def list_accepted_friends(conn: asyncpg.Connection, user_id: UUID) -> list[Friendship]:
    """Lists all accepted friendships for a user."""
    records = await conn.fetch(Fetch.LIST_ACCEPTED_FRIENDS, user_id)
    return Friendship.from_records(records)


async def list_pending_requests(conn: asyncpg.Connection, user_id: UUID) -> list[Friendship]:
    """Lists incoming pending friend requests for a user."""
    records = await conn.fetch(Fetch.LIST_PENDING_REQUESTS, user_id)
    return Friendship.from_records(records)


async def send_friend_request(
    conn: asyncpg.Connection, requester_id: UUID, addressee_id: UUID
) -> None:
    """Creates a new pending friend request entry."""
    try:
        await conn.execute(Write.SEND_FRIEND_REQUEST, requester_id, addressee_id)
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e


async def accept_friend_request(
    conn: asyncpg.Connection, requester_id: UUID, addressee_id: UUID
) -> None:
    """Marks a pending friend request as accepted."""
    status = await conn.execute(Write.ACCEPT_FRIEND_REQUEST, requester_id, addressee_id)
    if status == CommandStatus.UPDATE_ZERO:
        raise NotFoundError(
            entity=Entity.FRIENDSHIP, identifier=f"{requester_id}, {addressee_id}"
        )


async def remove_friendship(conn: asyncpg.Connection, user_a: UUID, user_b: UUID) -> None:
    """Deletes a friendship or pending request entry."""
    status = await conn.execute(Delete.REMOVE_FRIENDSHIP, user_a, user_b)
    if status == CommandStatus.DELETE_ZERO:
        raise NotFoundError(entity=Entity.FRIENDSHIP, identifier=f"{user_a}, {user_b}")


# Token Operations


async def get_access_token(
    conn: asyncpg.Connection, token_hash: str, *, for_update: bool = False
) -> AccessToken:
    """Retrieves an access token record by token hash."""
    query = _with_lock(Fetch.ACCESS_TOKEN, for_update)
    record = await conn.fetchrow(query, token_hash)
    if not record:
        raise NotFoundError(entity=Entity.ACCESS_TOKEN, identifier=token_hash)
    return AccessToken.from_record(record)


async def get_refresh_token(
    conn: asyncpg.Connection, token_hash: str, *, for_update: bool = False
) -> RefreshToken:
    """Retrieves a refresh token record by token hash."""
    query = _with_lock(Fetch.REFRESH_TOKEN, for_update)
    record = await conn.fetchrow(query, token_hash)
    if not record:
        raise NotFoundError(entity=Entity.REFRESH_TOKEN, identifier=token_hash)
    return RefreshToken.from_record(record)


async def create_access_token(conn: asyncpg.Connection, token: AccessToken) -> None:
    """Persists a new access token record."""
    try:
        await conn.execute(Write.INSERT_ACCESS_TOKEN, *token.to_args())
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e


async def create_refresh_token(conn: asyncpg.Connection, token: RefreshToken) -> None:
    """Persists a new refresh token record."""
    try:
        await conn.execute(Write.INSERT_REFRESH_TOKEN, *token.to_args())
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e


async def revoke_access_token(conn: asyncpg.Connection, token_hash: str) -> None:
    """Revokes a specific access token."""
    status = await conn.execute(Write.REVOKE_ACCESS_TOKEN, token_hash)
    if status == CommandStatus.UPDATE_ZERO:
        raise NotFoundError(entity=Entity.ACCESS_TOKEN, identifier=token_hash)


async def revoke_refresh_token(conn: asyncpg.Connection, token_hash: str) -> None:
    """Revokes a specific refresh token."""
    status = await conn.execute(Write.REVOKE_REFRESH_TOKEN, token_hash)
    if status == CommandStatus.UPDATE_ZERO:
        raise NotFoundError(entity=Entity.REFRESH_TOKEN, identifier=token_hash)


async def revoke_all_user_access_tokens(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Revokes all access tokens belonging to a user."""
    await conn.execute(Write.REVOKE_ALL_USER_ACCESS_TOKENS, user_id)


async def revoke_all_user_refresh_tokens(conn: asyncpg.Connection, user_id: UUID) -> None:
    """Revokes all refresh tokens belonging to a user."""
    await conn.execute(Write.REVOKE_ALL_USER_REFRESH_TOKENS, user_id)


async def purge_expired_access_tokens(conn: asyncpg.Connection) -> int:
    """Purges expired access tokens and returns deleted count."""
    status = await conn.execute(Delete.EXPIRED_ACCESS_TOKENS)
    return int(status.split(" ")[1])


async def purge_expired_refresh_tokens(conn: asyncpg.Connection) -> int:
    """Purges expired refresh tokens and returns deleted count."""
    status = await conn.execute(Delete.EXPIRED_REFRESH_TOKENS)
    return int(status.split(" ")[1])


# Group Operations


async def get_group_by_id(
    conn: asyncpg.Connection, group_id: UUID, *, for_update: bool = False
) -> Group:
    """Retrieves group details by group_id."""
    query = _with_lock(Fetch.GROUP_BY_ID, for_update)
    record = await conn.fetchrow(query, group_id)
    if not record:
        raise NotFoundError(entity=Entity.GROUP, identifier=str(group_id))
    return Group.from_record(record)


async def list_user_groups(conn: asyncpg.Connection, user_id: UUID) -> list[Group]:
    """Lists all groups joined by a specific user."""
    records = await conn.fetch(Fetch.LIST_USER_GROUPS, user_id)
    return Group.from_records(records)


async def list_group_memberships(conn: asyncpg.Connection, group_id: UUID) -> list[Membership]:
    """Lists all memberships of a specific group."""
    records = await conn.fetch(Fetch.LIST_GROUP_MEMBERSHIPS, group_id)
    return Membership.from_records(records)


async def create_group(conn: asyncpg.Connection, group: Group) -> Group:
    """Creates a new group record."""
    try:
        record = await conn.fetchrow(Write.CREATE_GROUP, *group.to_args())
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e

    if not record:
        raise NotFoundError(entity=Entity.GROUP, identifier=str(group.group_id))
    return group.update_from_record(record)


async def delete_group(conn: asyncpg.Connection, group_id: UUID, created_by: UUID) -> None:
    """Deletes a group restricted to creator authorization."""
    status = await conn.execute(Delete.DELETE_GROUP, group_id, created_by)
    if status == CommandStatus.DELETE_ZERO:
        raise NotFoundError(entity=Entity.GROUP, identifier=str(group_id))


async def get_group_memberships(conn: asyncpg.Connection, group_id: UUID) -> list[Membership]:
    """Retrieves user IDs of all members belonging to a specific group."""
    records = await conn.fetch(Fetch.LIST_GROUP_MEMBERSHIPS, group_id)
    return Membership.from_records(records)


# Membership Operations


async def get_membership(
    conn: asyncpg.Connection,
    group_id: UUID,
    user_id: UUID,
    *,
    for_update: bool = False,
) -> Membership:
    """Retrieves a group membership record."""
    query = _with_lock(Fetch.MEMBERSHIP_BY_IDS, for_update)
    record = await conn.fetchrow(query, group_id, user_id)
    if not record:
        raise NotFoundError(
            entity=Entity.MEMBERSHIP, identifier=f"Group:{group_id} User:{user_id}"
        )
    return Membership.from_record(record)


async def add_group_member(conn: asyncpg.Connection, membership: Membership) -> Membership:
    """Inserts a new user membership into a group."""
    try:
        record = await conn.fetchrow(Write.ADD_GROUP_MEMBER, *membership.to_args())
    except asyncpg.ForeignKeyViolationError as e:
        raise NotFoundError(entity=Entity.USER, identifier=str(membership.user_id)) from e
    except asyncpg.UniqueViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e

    if record is None:
        raise NotFoundError(entity=Entity.MEMBERSHIP, identifier=str(membership.pk))
    return membership.update_from_record(record)


async def remove_group_member(conn: asyncpg.Connection, group_id: UUID, user_id: UUID) -> None:
    """Removes a member from a group."""
    status = await conn.execute(Delete.REMOVE_GROUP_MEMBER, group_id, user_id)
    if status == CommandStatus.DELETE_ZERO:
        raise NotFoundError(
            entity=Entity.MEMBERSHIP, identifier=f"Group:{group_id} User:{user_id}"
        )


# Message Operations


async def get_dm_conversation_history(
    conn: asyncpg.Connection,
    user_a: UUID,
    user_b: UUID,
    before: datetime,
    limit: int,
) -> list[DirectMessage]:
    """Fetches historical direct messages between two users before a timestamp."""
    records = await conn.fetch(Fetch.DM_CONVERSATION_HISTORY, user_a, user_b, before, limit)
    return DirectMessage.from_records(records)


async def get_group_messages_timeline(
    conn: asyncpg.Connection,
    group_id: UUID,
    before: datetime,
    limit: int,
) -> list[GroupMessage]:
    """Fetches historical messages in a group before a timestamp."""
    records = await conn.fetch(Fetch.GROUP_MESSAGES_TIMELINE, group_id, before, limit)
    return GroupMessage.from_records(records)


async def send_direct_message(
    conn: asyncpg.Connection, message: DirectMessage
) -> DirectMessage:
    """Persists a new direct message record."""
    try:
        record = await conn.fetchrow(Write.SEND_DM, *message.to_args())
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e

    if not record:
        raise NotFoundError(entity=Entity.DIRECT_MESSAGE, identifier=str(message.message_id))
    return message.update_from_record(record)


async def send_group_message(conn: asyncpg.Connection, message: GroupMessage) -> GroupMessage:
    """Persists a new group message record."""
    try:
        record = await conn.fetchrow(Write.SEND_GROUP_MESSAGE, *message.to_args())
    except asyncpg.IntegrityConstraintViolationError as e:
        raise ConstraintViolationError.from_asyncpg(e) from e

    if not record:
        raise NotFoundError(entity=Entity.GROUP_MESSAGE, identifier=str(message.message_id))
    return message.update_from_record(record)
