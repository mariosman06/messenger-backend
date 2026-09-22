"""Database pool management, connections, and transactions."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import asyncpg
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
    wait_random_exponential,
)

from .enums import IsolationLevel
from .errors import (
    ConnectionPoolNotInitializedError,
    DatabaseConnectionError,
    DatabaseError,
    DatabaseTimeoutError,
    SerializationError,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages the PostgreSQL connection pool and transaction lifecycles."""

    def __init__(
        self,
        dsn: str,
        min_size: int = 5,
        max_size: int = 70,
        timeout: float = 10.0,
        command_timeout: float = 15.0,
    ) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._timeout = timeout
        self._command_timeout = command_timeout
        self._pool: asyncpg.Pool | None = None

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(OSError),
    )
    async def connect(self) -> asyncpg.Pool:
        """Initializes the database connection pool with retries."""
        if self._pool is not None:
            logger.debug("Database pool already initialized.")
            return self._pool

        logger.info("Initializing database connection pool...")
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            timeout=self._timeout,
            command_timeout=self._command_timeout,
        )
        logger.info("Database connection pool initialized successfully.")
        return self._pool

    async def disconnect(self) -> None:
        """Closes the connection pool."""
        if self._pool is None:
            return

        logger.info("Closing database connection pool...")
        await self._pool.close()
        self._pool = None
        logger.info("Database connection pool closed.")

    @property
    def pool(self) -> asyncpg.Pool:
        """Direct access to raw pool if strictly necessary."""
        if self._pool is None:
            raise ConnectionPoolNotInitializedError()
        return self._pool

    @asynccontextmanager
    async def connection(
        self, conn: asyncpg.Connection | None = None
    ) -> AsyncGenerator[asyncpg.Connection]:
        """Acquires a connection from the pool, or reuses an existing one."""
        if conn is not None:
            yield conn
            return

        if self._pool is None:
            raise ConnectionPoolNotInitializedError()

        try:
            async with self._pool.acquire() as new_conn:
                yield cast(asyncpg.Connection, new_conn)
        except asyncpg.InterfaceError as e:
            logger.error("Database connection lost: %s", e)
            raise DatabaseConnectionError(f"Database connection lost: {e}") from e
        except asyncpg.QueryCanceledError as e:
            logger.warning("Database query timed out: %s", e)
            raise DatabaseTimeoutError(f"Database query timed out: {e}") from e
        except asyncpg.PostgresError as e:
            logger.error("Postgres error: %s", e)
            raise DatabaseError(f"Postgres database error: {e}") from e

    @asynccontextmanager
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(min=0.1, max=1),
        retry=retry_if_exception_type(SerializationError),
        reraise=True,
    )
    async def transaction(
        self,
        conn: asyncpg.Connection | None = None,
        isolation: str = IsolationLevel.READ_COMMITTED,
    ) -> AsyncGenerator[asyncpg.Connection]:
        """Executes operations inside a transaction with automatic retry on serialization failures."""
        async with self.connection(conn=conn) as active_conn:
            try:
                async with active_conn.transaction(isolation=isolation):
                    yield active_conn
            except asyncpg.SerializationError as e:
                logger.warning("Serialization conflict; retrying transaction...")
                raise SerializationError(f"Serialization failure: {e}") from e
