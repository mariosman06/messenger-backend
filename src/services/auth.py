"""Authentication service managing token lifecycles and login flows."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

import asyncpg

import src.database.queries as db_queries
from src.config.settings import get_settings
from src.crypto.passwords import hash_password, needs_rehash, verify_password
from src.crypto.tokens import generate_raw_token, hash_token
from src.database.connection import get_transaction
from src.database.enums import Constraint as DBConstraint
from src.database.enums import Entity as DBEntity
from src.database.models import AccessToken, RefreshToken, User
from src.utils.timestamps import expiration_ts

from .errors import (
    InvalidCredentialsError,
    InvalidTokenError,
    TokenExpiredError,
    TokenRevokedError,
    handle_db_constraint_error,
    handle_db_not_found_error,
)

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(slots=True, frozen=True)
class TokenPair:
    """Encapsulates raw access and refresh tokens alongside expiration metadata."""

    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime

    @classmethod
    def generate(cls) -> Self:
        """Generates a fresh pair of raw cryptographic tokens with configured expiration targets."""
        return cls(
            access_token=generate_raw_token(),
            refresh_token=generate_raw_token(),
            access_token_expires_at=expiration_ts(settings.auth.access_token_ttl),
            refresh_token_expires_at=expiration_ts(settings.auth.refresh_token_ttl),
        )


@handle_db_constraint_error()
async def register(username: str, password: str) -> tuple[User, TokenPair]:
    """Registers a new user account and issues an initial token pair."""
    password_hash = hash_password(password)
    user_model = User(username=username, password_hash=password_hash)
    token_pair = TokenPair.generate()

    async with get_transaction() as conn:
        user = await db_queries.create_user(conn, user_model)
        await _issue_token_pair(conn, user.user_id, token_pair)
        logger.info("User registered successfully: %s (id: %s)", user.username, user.user_id)
        return user, token_pair


@handle_db_constraint_error(
    overrides={
        DBConstraint.FK_ACCESS_TOKENS_USER_ID: InvalidCredentialsError,
        DBConstraint.FK_REFRESH_TOKENS_USER_ID: InvalidCredentialsError,
    }
)
@handle_db_not_found_error(overrides={DBEntity.USER: InvalidCredentialsError})
async def login(username: str, password: str) -> tuple[User, TokenPair]:
    """Authenticates credentials, handles password re-hashing, and issues fresh tokens."""
    token_pair = TokenPair.generate()

    async with get_transaction() as conn:
        user = await db_queries.get_user_by_username(conn, username)

        if not verify_password(password, user.password_hash):
            logger.warning("Failed login attempt for username: %s", username)
            raise InvalidCredentialsError()

        if user.deactivated:
            logger.info(
                "Reactivating deactivated account during login for user: %s (id: %s)",
                user.username,
                user.user_id,
            )
            await db_queries.reactivate_user(conn, user.user_id)

        if needs_rehash(user.password_hash):
            logger.info("Rehashing outdated password for user: %s", user.user_id)
            new_hash = hash_password(password)
            await db_queries.update_user_password(
                conn, user.user_id, new_hash, user.password_hash
            )

        await _issue_token_pair(conn, user.user_id, token_pair)
        logger.info("User logged in successfully: %s (id: %s)", user.username, user.user_id)
        return user, token_pair


@handle_db_constraint_error()
@handle_db_not_found_error(overrides={DBEntity.REFRESH_TOKEN: InvalidTokenError})
async def refresh(raw_refresh_token: str) -> TokenPair:
    """Rotates a refresh token into a new pair while enforcing reuse detection security."""
    refresh_hash = hash_token(raw_refresh_token)
    token_pair = TokenPair.generate()
    is_reused = False

    async with get_transaction() as conn:
        token_record = await db_queries.get_refresh_token(conn, refresh_hash, for_update=True)

        if token_record.is_revoked:
            logger.warning(
                "Token reuse detected for user: %s! Revoking all active tokens.",
                token_record.user_id,
            )
            await db_queries.revoke_all_user_access_tokens(conn, token_record.user_id)
            await db_queries.revoke_all_user_refresh_tokens(conn, token_record.user_id)
            is_reused = True
        elif token_record.is_expired:
            logger.info(
                "Refresh attempt with expired token for user: %s", token_record.user_id
            )
            raise TokenExpiredError()
        else:
            await db_queries.revoke_refresh_token(conn, refresh_hash)
            await _issue_token_pair(conn, token_record.user_id, token_pair)
            logger.info("Tokens rotated successfully for user: %s", token_record.user_id)

    if is_reused:
        raise TokenRevokedError()

    return token_pair


@handle_db_not_found_error(
    overrides={
        DBEntity.REFRESH_TOKEN: None,
        DBEntity.ACCESS_TOKEN: None,
    }
)
async def logout(raw_refresh_token: str, raw_access_token: str | None = None) -> None:
    """Revokes refresh and optional access tokens silently."""
    refresh_hash = hash_token(raw_refresh_token)
    access_hash = hash_token(raw_access_token) if raw_access_token else None

    async with get_transaction() as conn:
        await db_queries.revoke_refresh_token(conn, refresh_hash)

        if access_hash:
            await db_queries.revoke_access_token(conn, access_hash)

    logger.info("User session logged out successfully.")


async def _issue_token_pair(
    conn: asyncpg.Connection, user_id: UUID, token_pair: TokenPair
) -> None:
    """Hashes and persists a TokenPair to the database storage layer."""
    await db_queries.create_access_token(
        conn,
        AccessToken(
            token_hash=hash_token(token_pair.access_token),
            user_id=user_id,
            expires_at=token_pair.access_token_expires_at,
        ),
    )
    await db_queries.create_refresh_token(
        conn,
        RefreshToken(
            token_hash=hash_token(token_pair.refresh_token),
            user_id=user_id,
            expires_at=token_pair.refresh_token_expires_at,
        ),
    )
