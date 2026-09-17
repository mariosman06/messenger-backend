"""Service exceptions and database error translation decorators."""

import functools
from collections.abc import Callable
from typing import Any
from uuid import UUID

import src.database.errors as db_err
from src.database.enums import Constraint as DBConstraint
from src.database.enums import Entity as DBEntity


class ServiceError(Exception):
    """Base exception for all domain service operations."""

    status_code: int = 500

    def __init__(self, message: str = "An unexpected error occurred.") -> None:
        super().__init__(message)
        self.message = message


# Authentication & Authorization Errors


class UserAlreadyExistsError(ServiceError):
    """Raised during registration if the requested username is already taken."""

    status_code = 409

    def __init__(self, username: str) -> None:
        super().__init__(f"Username '{username}' is already taken.")
        self.username = username


class InvalidCredentialsError(ServiceError):
    """Raised when authentication fails due to incorrect credentials."""

    status_code = 401

    def __init__(self, message: str = "Invalid username or password.") -> None:
        super().__init__(message)


class InvalidTokenError(ServiceError):
    """Raised when an API token is malformed, unrecognized, or inactive."""

    status_code = 401

    def __init__(self, message: str = "Invalid or expired token.") -> None:
        super().__init__(message)


class TokenExpiredError(ServiceError):
    """Raised when an authentication token has passed its expiration time."""

    status_code = 401

    def __init__(self, message: str = "Token has expired.") -> None:
        super().__init__(message)


class TokenRevokedError(ServiceError):
    """Raised when a revoked or reused token attempt triggers session termination."""

    status_code = 401

    def __init__(
        self,
        message: str = "Security alert: Token reuse detected. All active sessions revoked.",
    ) -> None:
        super().__init__(message)


# User Domain Errors


class UserNotFoundError(ServiceError):
    """Raised when a requested user profile does not exist."""

    status_code = 404

    def __init__(self, identifier: str | UUID) -> None:
        super().__init__(f"User '{identifier}' was not found.")
        self.identifier = identifier


# Friendship Domain Errors


class FriendshipError(ServiceError):
    """Base exception for friendship-related domain failures."""

    status_code = 400


class SelfFriendshipError(FriendshipError):
    """Raised when a user attempts to create a relationship with themselves."""

    status_code = 400

    def __init__(self, message: str = "Cannot send a friend request to yourself.") -> None:
        super().__init__(message)


class FriendRequestAlreadyExistsError(FriendshipError):
    """Raised when a friendship or pending request already exists between two users."""

    status_code = 409

    def __init__(self, addressee_id: str | UUID) -> None:
        super().__init__(
            f"A friend request or active friendship already exists with user '{addressee_id}'."
        )
        self.addressee_id = addressee_id


class FriendRequestNotFoundError(FriendshipError):
    """Raised when an operation targets a non-existent friend request."""

    status_code = 404

    def __init__(self, requester_id: str | UUID) -> None:
        super().__init__(f"No pending friend request found from user '{requester_id}'.")
        self.requester_id = requester_id


# Group Domain Errors


class GroupError(ServiceError):
    """Base exception for group-related domain failures."""

    status_code = 400


class GroupNotFoundError(GroupError):
    """Raised when a targeted group chat does not exist."""

    status_code = 404

    def __init__(self, group_id: str | UUID) -> None:
        super().__init__(f"Group '{group_id}' was not found.")
        self.group_id = group_id


class GroupNameAlreadyExistsError(GroupError):
    """Raised when a creator attempts to reuse a group name they already own."""

    status_code = 409

    def __init__(self, creator_id: str | UUID, name: str) -> None:
        super().__init__(f"Group '{name}' already exists for creator '{creator_id}'.")
        self.creator_id = creator_id
        self.name = name


class AlreadyGroupMemberError(GroupError):
    """Raised when adding a user to a group they already belong to."""

    status_code = 409

    def __init__(self, user_id: str | UUID, group_id: str | UUID) -> None:
        super().__init__(f"User '{user_id}' is already a member of group '{group_id}'.")
        self.user_id = user_id
        self.group_id = group_id


class NotGroupMemberError(GroupError):
    """Raised when a non-member attempts an action restricted to group members."""

    status_code = 403

    def __init__(self, user_id: str | UUID, group_id: str | UUID) -> None:
        super().__init__(f"User '{user_id}' is not an active member of group '{group_id}'.")
        self.user_id = user_id
        self.group_id = group_id


class InsufficientGroupPermissionError(GroupError):
    """Raised when a non-owner/non-admin user attempts an administrative operation."""

    status_code = 403

    def __init__(
        self, message: str = "Administrative permissions required for this group."
    ) -> None:
        super().__init__(message)


# Messaging Domain Errors


class MessageError(ServiceError):
    """Base exception for messaging operations."""

    status_code = 400


class DirectMessageNotAllowedError(MessageError):
    """Raised when sending a direct message to a user without active friendship."""

    status_code = 403

    def __init__(self, recipient_id: str | UUID) -> None:
        super().__init__(
            f"Cannot send message. You are not friends with user '{recipient_id}'."
        )
        self.recipient_id = recipient_id


class GroupMessageNotAllowedError(MessageError):
    """Raised when sending a group message without active group membership."""

    status_code = 403

    def __init__(self, group_id: str | UUID) -> None:
        super().__init__(f"Cannot send message. You are not a member of group '{group_id}'.")
        self.group_id = group_id


# Error Translation Mapping


CONSTRAINT_MAP: dict[DBConstraint | str, Callable[..., ServiceError]] = {
    DBConstraint.UQ_USERS_USERNAME: lambda **kw: UserAlreadyExistsError(
        username=kw.get("username", "unknown")
    ),
    DBConstraint.PK_FRIENDSHIPS: lambda **kw: FriendRequestAlreadyExistsError(
        addressee_id=kw.get("addressee_id", "unknown")
    ),
    DBConstraint.FK_FRIENDSHIPS_REQUESTER_ID: lambda **kw: UserNotFoundError(
        identifier=kw.get("requester_id", "unknown")
    ),
    DBConstraint.FK_FRIENDSHIPS_ADDRESSEE_ID: lambda **kw: UserNotFoundError(
        identifier=kw.get("addressee_id", "unknown")
    ),
    DBConstraint.FK_ACCESS_TOKENS_USER_ID: lambda **kw: UserNotFoundError(
        identifier=kw.get("user_id", "unknown")
    ),
    DBConstraint.FK_REFRESH_TOKENS_USER_ID: lambda **kw: UserNotFoundError(
        identifier=kw.get("user_id", "unknown")
    ),
    DBConstraint.UQ_GROUPS_CREATED_BY_NAME: lambda **kw: GroupNameAlreadyExistsError(
        creator_id=kw.get("creator_id", "unknown"), name=kw.get("name", "unknown")
    ),
    DBConstraint.FK_GROUPS_CREATED_BY: lambda **kw: UserNotFoundError(
        identifier=kw.get("user_id", "unknown")
    ),
    DBConstraint.FK_MEMBERSHIPS_GROUP_ID: lambda **kw: GroupNotFoundError(
        group_id=kw.get("group_id", "unknown")
    ),
    DBConstraint.PK_MEMBERSHIPS: lambda **kw: AlreadyGroupMemberError(
        user_id=kw.get("user_id", "unknown"), group_id=kw.get("group", "unknown")
    ),
    DBConstraint.FK_MEMBERSHIPS_USER_ID: lambda **kw: UserNotFoundError(
        identifier=kw.get("user_id", "unknown")
    ),
    DBConstraint.FK_DM_SENDER_ID: lambda **kw: UserNotFoundError(
        identifier=kw.get("sender_id", "unknown")
    ),
    DBConstraint.FK_DM_RECIPIENT_ID: lambda **kw: DirectMessageNotAllowedError(
        recipient_id=kw.get("recipient_id", "unknown")
    ),
    DBConstraint.FK_GROUP_MESSAGES_GROUP_ID: lambda **kw: GroupMessageNotAllowedError(
        group_id=kw.get("group_id", "unknown")
    ),
    DBConstraint.FK_GROUP_MESSAGES_SENDER_ID: lambda **kw: NotGroupMemberError(
        user_id=kw.get("user_id", "unknown"), group_id=kw.get("group_id", "unknown")
    ),
}

ENTITY_NOT_FOUND_MAP: dict[DBEntity | str, Callable[..., ServiceError]] = {
    DBEntity.USER: lambda **kw: UserNotFoundError(
        identifier=kw.get("identifier") or kw.get("user_id", "unknown")
    ),
    DBEntity.GROUP: lambda **kw: GroupNotFoundError(
        group_id=kw.get("identifier") or kw.get("group_id", "unknown")
    ),
    DBEntity.MEMBERSHIP: lambda **kw: NotGroupMemberError(
        user_id=kw.get("actor_id") or kw.get("user_id", "unknown"),
        group_id=kw.get("group_id", "unknown"),
    ),
    DBEntity.FRIENDSHIP: lambda **kw: FriendRequestNotFoundError(
        requester_id=kw.get("identifier") or kw.get("requester_id", "unknown")
    ),
}


# Decorators


def handle_db_constraint_error(
    overrides: dict[str, Callable[..., ServiceError] | type[ServiceError]] | None = None,
    **caller_context: Any,
) -> Callable:
    """Intercepts database ConstraintViolationError exceptions and maps them to domain exceptions."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except db_err.ConstraintViolationError as e:
                raw_constraint = e.constraint.lower() if e.constraint else None
                normalized_overrides = {k.lower(): v for k, v in (overrides or {}).items()}
                active_map = {**CONSTRAINT_MAP, **normalized_overrides}

                if raw_constraint and raw_constraint in active_map:
                    ctx = {
                        "constraint": raw_constraint,
                        "table": e.table,
                        "db_error": e,
                        **kwargs,
                        **caller_context,
                    }
                    handler = active_map[raw_constraint]

                    if isinstance(handler, type) and issubclass(handler, Exception):
                        raise handler() from e

                    raise handler(**ctx) from e

                raise

        return wrapper

    return decorator


def handle_db_not_found_error(
    overrides: dict[DBEntity | str, Callable[..., ServiceError] | type[ServiceError] | None]
    | None = None,
    **caller_context: Any,
) -> Callable:
    """Intercepts database NotFoundError exceptions and converts or suppresses them."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except db_err.NotFoundError as e:
                entity = getattr(e, "entity", None)
                active_map = {**ENTITY_NOT_FOUND_MAP, **(overrides or {})}

                if entity and entity in active_map:
                    handler = active_map[entity]

                    if handler is None:
                        return None

                    if isinstance(handler, type) and issubclass(handler, Exception):
                        raise handler() from e

                    ctx = {
                        "identifier": getattr(e, "identifier", None),
                        "db_error": e,
                        **kwargs,
                        **caller_context,
                    }
                    raise handler(**ctx) from e

                raise

        return wrapper

    return decorator
