"""User management service handling lookups and account lifecycle mutations."""

import logging
from uuid import UUID

import src.database.queries as db_queries
from src.database.connection import get_conn, get_transaction
from src.database.models import User

from .errors import handle_db_not_found_error

logger = logging.getLogger(__name__)


@handle_db_not_found_error()
async def get_by_username(username: str) -> User:
    """Retrieves a public user record by unique username."""
    async with get_conn() as conn:
        return await db_queries.get_user_by_username(conn, username)


@handle_db_not_found_error()
async def get_by_id(user_id: UUID) -> User:
    """Retrieves a user record by primary key identifier."""
    async with get_conn() as conn:
        return await db_queries.get_user_by_id(conn, user_id)


@handle_db_not_found_error()
async def deactivate_account(user_id: UUID) -> None:
    """Flags an active user account as deactivated."""
    async with get_transaction() as conn:
        await db_queries.deactivate_user(conn, user_id)
        logger.info("User account deactivated: %s", user_id)


@handle_db_not_found_error()
async def reactivate_account(user_id: UUID) -> None:
    """Reactivates a previously deactivated user account."""
    async with get_transaction() as conn:
        await db_queries.reactivate_user(conn, user_id)
        logger.info("User account reactivated: %s", user_id)


@handle_db_not_found_error()
async def delete_account(user_id: UUID) -> None:
    """Hard-deletes a user account record from the system."""
    async with get_transaction() as conn:
        await db_queries.delete_user(conn, user_id)
        logger.info("User account deleted permanently: %s", user_id)
