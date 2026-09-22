"""User management service handling account lifecycles and social friendships."""

import logging
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import DatabaseManager
from src.database.models import Friendship, User

from .errors import (
    SelfFriendshipError,
    handle_db_constraint_error,
    handle_db_not_found_error,
)

logger = logging.getLogger(__name__)


class UserService:
    """Handles profile lookups, account lifecycle events, and user social graphs."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    # Account and Profile Management

    @handle_db_not_found_error()
    async def get_by_username(self, username: str) -> User:
        """Retrieves a public user record by unique username."""
        async with self._db.connection() as conn:
            return await db_queries.get_user_by_username(conn, username)

    @handle_db_not_found_error()
    async def get_by_id(self, user_id: UUID) -> User:
        """Retrieves a user record by primary key identifier."""
        async with self._db.connection() as conn:
            return await db_queries.get_user_by_id(conn, user_id)

    @handle_db_not_found_error()
    async def deactivate_account(self, user_id: UUID) -> None:
        """Flags an active user account as deactivated."""
        async with self._db.transaction() as conn:
            await db_queries.deactivate_user(conn, user_id)
            logger.info("User account deactivated: %s", user_id)

    @handle_db_not_found_error()
    async def reactivate_account(self, user_id: UUID) -> None:
        """Reactivates a previously deactivated user account."""
        async with self._db.transaction() as conn:
            await db_queries.reactivate_user(conn, user_id)
            logger.info("User account reactivated: %s", user_id)

    @handle_db_not_found_error()
    async def delete_account(self, user_id: UUID) -> None:
        """Hard-deletes a user account record from the system."""
        async with self._db.transaction() as conn:
            await db_queries.delete_user(conn, user_id)
            logger.info("User account deleted permanently: %s", user_id)

    # Friendship and Social Graph Operations

    @handle_db_constraint_error()
    async def send_friend_request(self, requester_id: UUID, addressee_id: UUID) -> None:
        """Sends a pending friend request from one user to another."""
        if requester_id == addressee_id:
            logger.warning(
                "User %s attempted to send a friend request to themselves.", requester_id
            )
            raise SelfFriendshipError()

        async with self._db.transaction() as conn:
            await db_queries.send_friend_request(conn, requester_id, addressee_id)
            logger.info("Friend request sent from %s to %s.", requester_id, addressee_id)

    @handle_db_not_found_error()
    async def accept_friend_request(self, addressee_id: UUID, requester_id: UUID) -> None:
        """Accepts an incoming pending friend request."""
        async with self._db.transaction() as conn:
            await db_queries.accept_friend_request(conn, requester_id, addressee_id)
            logger.info("Friend request from %s accepted by %s.", requester_id, addressee_id)

    @handle_db_not_found_error()
    async def remove_or_decline_friendship(self, user_a: UUID, user_b: UUID) -> None:
        """Removes an active friendship, pending request, or declined relationship."""
        async with self._db.transaction() as conn:
            await db_queries.remove_friendship(conn, user_a, user_b)
            logger.info("Friendship relationship removed between %s and %s.", user_a, user_b)

    @handle_db_not_found_error()
    async def get_friendship_status(self, user_a: UUID, user_b: UUID) -> Friendship:
        """Retrieves the current friendship record between two users."""
        async with self._db.connection() as conn:
            return await db_queries.get_friendship_status(conn, user_a, user_b)

    async def get_friends(self, user_id: UUID) -> list[Friendship]:
        """Retrieves all accepted friendships for a user."""
        async with self._db.connection() as conn:
            return await db_queries.list_accepted_friends(conn, user_id)

    async def get_pending_friend_requests(self, user_id: UUID) -> list[Friendship]:
        """Retrieves all incoming pending friend requests for a user."""
        async with self._db.connection() as conn:
            return await db_queries.list_pending_requests(conn, user_id)
