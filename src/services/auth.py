"""Authentication service managing token lifecycles, local caching, and login flows."""

import logging
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Self, cast
from uuid import UUID

import asyncpg
from cachetools import TTLCache
from redis.asyncio import Redis

import src.database.queries as db_queries
from src.config.settings import AuthConfig, get_settings
from src.crypto.passwords import hash_password, needs_rehash, verify_password
from src.crypto.tokens import generate_raw_token, hash_token
from src.database.connection import DatabaseManager
from src.database.enums import Constraint as DBConstraint
from src.database.enums import Entity as DBEntity
from src.database.models import AccessToken, RefreshToken, User
from src.redis.events import EventType, TokenRevokedEvent, UserInvalidatedEvent
from src.redis.stream import publish_stream_event
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


class TokenCache:
    """Worker-local RAM cache using TTLCache for fast path token validation."""

    def __init__(self, maxsize: int = 10000, ttl: int = 300) -> None:
        self._cache: MutableMapping[str, User] = cast(
            MutableMapping[str, User],
            TTLCache(maxsize=maxsize, ttl=ttl),
        )

    def clear(self) -> None:
        """Evicts all cached tokens and users from local RAM."""
        self._cache.clear()

    def get(self, token_hash: str) -> User | None:
        """Retrieves a cached User instance by token hash."""
        return self._cache.get(token_hash)

    def set(self, token_hash: str, user: User) -> None:
        """Stores a User instance keyed by token hash in local RAM."""
        self._cache[token_hash] = user

    def evict(self, token_hash: str) -> None:
        """Synchronously drops a single token from this worker's RAM."""
        self._cache.pop(token_hash, None)

    def evict_user(self, user_id: UUID | str) -> None:
        """Evicts all active cached token hashes belonging to a specific user."""
        target_id = str(user_id)
        hashes_to_remove = [
            t_hash for t_hash, user in self._cache.items() if str(user.user_id) == target_id
        ]
        for t_hash in hashes_to_remove:
            self._cache.pop(t_hash, None)

    async def handle_invalidation_event(self, event_dict: dict[str, Any]) -> None:
        """Dispatched by the Redis Stream consumer to invalidate local RAM."""
        event_type = event_dict.get("event")

        if event_type == EventType.TOKEN_REVOKED:
            if token_hash := event_dict.get("token_hash"):
                self.evict(token_hash)

        elif event_type == EventType.USER_INVALIDATED:
            if user_id := event_dict.get("user_id"):
                self.evict_user(user_id)


@dataclass(slots=True, frozen=True)
class TokenPair:
    """Encapsulates raw access and refresh tokens alongside expiration metadata."""

    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime

    @classmethod
    def generate(cls, access_ttl: int, refresh_ttl: int) -> Self:
        """Generates a fresh pair of raw cryptographic tokens with configured expirations."""
        return cls(
            access_token=generate_raw_token(),
            refresh_token=generate_raw_token(),
            access_token_expires_at=expiration_ts(access_ttl),
            refresh_token_expires_at=expiration_ts(refresh_ttl),
        )


class AuthService:
    """Handles authentication business logic, credentials, and token lifecycles."""

    def __init__(
        self,
        db: DatabaseManager,
        redis: Redis,
        cache: TokenCache,
        auth_settings: AuthConfig | None = None,
    ) -> None:
        self._db = db
        self._redis = redis
        self._cache = cache
        self._settings = auth_settings or get_settings().auth

    def _generate_token_pair(self) -> TokenPair:
        return TokenPair.generate(
            access_ttl=self._settings.access_token_ttl,
            refresh_ttl=self._settings.refresh_token_ttl,
        )

    @handle_db_constraint_error()
    async def register(self, username: str, password: str) -> tuple[User, TokenPair]:
        """Registers a new user account and issues an initial token pair."""
        password_hash = await hash_password(password)
        user_model = User(username=username, password_hash=password_hash)
        token_pair = self._generate_token_pair()

        async with self._db.transaction() as conn:
            user = await db_queries.create_user(conn, user_model)
            await self._issue_token_pair(conn, user.user_id, token_pair)

        logger.info("User registered successfully: %s (id: %s)", user.username, user.user_id)
        return user, token_pair

    @handle_db_constraint_error(
        overrides={
            DBConstraint.FK_ACCESS_TOKENS_USER_ID: InvalidCredentialsError,
            DBConstraint.FK_REFRESH_TOKENS_USER_ID: InvalidCredentialsError,
        }
    )
    @handle_db_not_found_error(overrides={DBEntity.USER: InvalidCredentialsError})
    async def login(self, username: str, password: str) -> tuple[User, TokenPair]:
        """Authenticates credentials, handles password re-hashing, and issues fresh tokens."""
        token_pair = self._generate_token_pair()
        cache_needs_invalidation = False

        async with self._db.transaction() as conn:
            user = await db_queries.get_user_by_username(conn, username)

            if not await verify_password(password, user.password_hash):
                logger.warning("Failed login attempt for username: %s", username)
                raise InvalidCredentialsError()

            if user.deactivated:
                logger.info("Reactivating account during login for user: %s", user.user_id)
                await db_queries.reactivate_user(conn, user.user_id)
                cache_needs_invalidation = True

            if await needs_rehash(user.password_hash):
                logger.info("Rehashing outdated password for user: %s", user.user_id)
                new_hash = await hash_password(password)
                await db_queries.update_user_password(
                    conn, user.user_id, new_hash, user.password_hash
                )
                cache_needs_invalidation = True

            await self._issue_token_pair(conn, user.user_id, token_pair)

        # Broadcast invalidation via Redis Streams only after DB transaction commits
        if cache_needs_invalidation:
            await publish_stream_event(self._redis, UserInvalidatedEvent(user_id=user.user_id))

        logger.info("User logged in successfully: %s (id: %s)", user.username, user.user_id)
        return user, token_pair

    @handle_db_constraint_error()
    @handle_db_not_found_error(overrides={DBEntity.REFRESH_TOKEN: InvalidTokenError})
    async def refresh(self, raw_refresh_token: str) -> TokenPair:
        """Rotates a refresh token into a new pair while enforcing reuse detection security."""
        refresh_hash = hash_token(raw_refresh_token)
        token_pair = self._generate_token_pair()
        is_reused = False
        user_id = None

        async with self._db.transaction() as conn:
            token_record = await db_queries.get_refresh_token(
                conn, refresh_hash, for_update=True
            )
            user_id = token_record.user_id

            if token_record.is_revoked:
                logger.warning("Token reuse detected for user: %s!", user_id)
                await db_queries.revoke_all_user_access_tokens(conn, user_id)
                await db_queries.revoke_all_user_refresh_tokens(conn, user_id)
                is_reused = True
            elif token_record.is_expired:
                logger.info("Refresh attempt with expired token for user: %s", user_id)
                raise TokenExpiredError()
            else:
                await db_queries.revoke_refresh_token(conn, refresh_hash)
                await self._issue_token_pair(conn, user_id, token_pair)
                logger.info("Tokens rotated successfully for user: %s", user_id)

        # Post-transaction cache invalidation via Redis Streams
        if is_reused and user_id:
            await publish_stream_event(self._redis, UserInvalidatedEvent(user_id=user_id))
            raise TokenRevokedError()
        else:
            await publish_stream_event(self._redis, TokenRevokedEvent(token_hash=refresh_hash))

        return token_pair

    @handle_db_not_found_error(
        overrides={
            DBEntity.REFRESH_TOKEN: None,
            DBEntity.ACCESS_TOKEN: None,
        }
    )
    async def logout(
        self, raw_refresh_token: str, raw_access_token: str | None = None
    ) -> None:
        """Revokes refresh and optional access tokens across DB, local RAM, and Redis stream."""
        refresh_hash = hash_token(raw_refresh_token)
        access_hash = hash_token(raw_access_token) if raw_access_token else None

        # Step 1: Revoke in PostgreSQL
        async with self._db.transaction() as conn:
            await db_queries.revoke_refresh_token(conn, refresh_hash)
            if access_hash:
                await db_queries.revoke_access_token(conn, access_hash)

        # Step 2: Synchronous local eviction in current worker RAM
        if access_hash:
            self._cache.evict(access_hash)

        # Step 3: Broadcast stream event to all other worker nodes
        await publish_stream_event(self._redis, TokenRevokedEvent(token_hash=refresh_hash))
        if access_hash:
            await publish_stream_event(self._redis, TokenRevokedEvent(token_hash=access_hash))

        logger.info("User session logged out successfully.")

    async def _issue_token_pair(
        self, conn: asyncpg.Connection, user_id: UUID, token_pair: TokenPair
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
