"""Database pool management, connections and transactions."""

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

_pool: asyncpg.Pool | None = None


# Pool Management


@retry(
    stop=stop_after_attempt(10),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(OSError),
)
async def init_pool(dsn: str) -> asyncpg.Pool | None:
    """Initializes the global database connection pool."""
    global _pool
    if _pool is not None:
        logger.debug("Database pool already initialized.")
        return _pool

    logger.info("Initializing database connection pool...")
    _pool = await asyncpg.create_pool(dsn=dsn)
    logger.info("Database connection pool initialized successfully.")
    return _pool


async def get_pool() -> asyncpg.Pool:
    """Retrieves the active global connection pool."""
    global _pool
    if _pool is None:
        logger.error("Attempted to access database pool before initialization.")
        raise ConnectionPoolNotInitializedError()

    return _pool


async def close_pool() -> None:
    """Closes the global connection pool and resets internal state."""
    global _pool
    if _pool is None:
        return

    logger.info("Closing database connection pool...")
    await _pool.close()
    _pool = None
    logger.info("Database connection pool closed.")


# Connection & Transaction Contexts


@asynccontextmanager
async def get_conn(
    pool: asyncpg.Pool | None = None, conn: asyncpg.Connection | None = None
) -> AsyncGenerator[asyncpg.Connection]:
    """Acquires or reuses a database connection context."""
    global _pool

    if conn is not None:
        yield conn
        return

    active_pool = pool or _pool
    if active_pool is None:
        logger.error("No active database pool available for connection acquisition.")
        raise ConnectionPoolNotInitializedError()

    try:
        async with active_pool.acquire() as new_conn:
            yield cast(asyncpg.Connection, new_conn)
    except asyncpg.InterfaceError as e:
        logger.error("Database connection lost or interface failure: %s", e)
        raise DatabaseConnectionError(
            f"Database connection lost or interface failure: {e}."
        ) from e
    except asyncpg.QueryCanceledError as e:
        logger.warning("Database operation timed out: %s", e)
        raise DatabaseTimeoutError(f"Database operation timed out: {e}.") from e
    except asyncpg.PostgresError as e:
        logger.error("PostgreSQL database error: %s", e)
        raise DatabaseError(f"Postgres database error: {e}.") from e


@asynccontextmanager
@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(min=0.1, max=1),
    retry=retry_if_exception_type(SerializationError),
    reraise=True,
)
async def get_transaction(
    pool: asyncpg.Pool | None = None,
    conn: asyncpg.Connection | None = None,
    isolation: str = IsolationLevel.READ_COMMITTED,
) -> AsyncGenerator[asyncpg.Connection]:
    """Executes operations inside a transaction block with automatic serialization retries."""
    async with get_conn(pool=pool, conn=conn) as active_conn:
        try:
            async with active_conn.transaction(isolation=isolation):
                yield active_conn
        except asyncpg.SerializationError as e:
            logger.warning("Serialization conflict during transaction; retrying...")
            raise SerializationError(
                f"Serialization failure during concurrent transaction: {e}."
            ) from e
