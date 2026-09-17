"""Friendship service CRUD operations."""

import logging
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import get_conn, get_transaction
from src.database.models import Friendship

from .errors import SelfFriendshipError, handle_db_constraint_error, handle_db_not_found_error

logger = logging.getLogger(__name__)


@handle_db_constraint_error()
async def send_request(requester_id: UUID, addressee_id: UUID) -> None:
    """Sends a pending friend request from one user to another."""
    if requester_id == addressee_id:
        logger.warning(
            "User %s attempted to send a friend request to themselves.", requester_id
        )
        raise SelfFriendshipError()

    async with get_transaction() as conn:
        await db_queries.send_friend_request(conn, requester_id, addressee_id)
        logger.info("Friend request sent from %s to %s.", requester_id, addressee_id)


@handle_db_not_found_error()
async def accept_request(addressee_id: UUID, requester_id: UUID) -> None:
    """Accepts an incoming pending friend request."""
    async with get_transaction() as conn:
        await db_queries.accept_friend_request(conn, requester_id, addressee_id)
        logger.info("Friend request from %s accepted by %s.", requester_id, addressee_id)


@handle_db_not_found_error()
async def remove_or_decline_friendship(user_a: UUID, user_b: UUID) -> None:
    """Removes an active friendship, pending request, or declined relationship between two users."""
    async with get_transaction() as conn:
        await db_queries.remove_friendship(conn, user_a, user_b)
        logger.info("Friendship relationship removed between %s and %s.", user_a, user_b)


@handle_db_not_found_error()
async def get_status(user_a: UUID, user_b: UUID) -> Friendship:
    """Retrieves the current friendship record between two users."""
    async with get_conn() as conn:
        return await db_queries.get_friendship_status(conn, user_a, user_b)


async def get_friends(user_id: UUID) -> list[Friendship]:
    """Retrieves all accepted friendships for a user."""
    async with get_conn() as conn:
        return await db_queries.list_accepted_friends(conn, user_id)


async def get_pending(user_id: UUID) -> list[Friendship]:
    """Retrieves all incoming pending friend requests for a user."""
    async with get_conn() as conn:
        return await db_queries.list_pending_requests(conn, user_id)
