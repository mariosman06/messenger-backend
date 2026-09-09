"""Database exceptions and driver error translation utilities."""

from typing import Self

import asyncpg


class DatabaseError(Exception):
    """Base exception for all database operations."""

    def __init__(self, message: str = "An unexpected database error occurred."):
        super().__init__(message)


class ConnectionPoolNotInitializedError(DatabaseError, RuntimeError):
    """Raised when an operation requires an active pool that has not been initialized."""

    def __init__(
        self,
        message: str = "The database connection pool has not been initialized.",
    ):
        super().__init__(message)


class DatabaseConnectionError(DatabaseError):
    """Raised when connection to the database drops or fails to establish."""

    def __init__(self, message: str = "Could not establish connection to the database."):
        super().__init__(message)


class DatabaseTimeoutError(DatabaseError):
    """Raised when a database query operation times out."""

    def __init__(self, message: str = "The database operation timed out."):
        super().__init__(message)


class SerializationError(DatabaseError):
    """Raised when a transaction fails due to concurrent update conflicts."""

    def __init__(
        self,
        message: str = "Transaction failed due to concurrent update conflicts.",
    ):
        super().__init__(message)


class NotFoundError(DatabaseError):
    """Raised when a requested database entity or record does not exist."""

    def __init__(self, entity: str | None = None, identifier: str | None = None):
        message = f"{entity} with identifier: {identifier} not found."
        super().__init__(message)
        self.entity = entity
        self.identifier = identifier


class ConstraintViolationError(DatabaseError):
    """Raised when an operation violates a unique, foreign key, or check constraint."""

    def __init__(self, table: str | None = None, constraint: str | None = None):
        message = f"{constraint} violation on table: {table}."
        super().__init__(message)
        self.table = table
        self.constraint = constraint

    @classmethod
    def from_asyncpg(cls, e: asyncpg.PostgresError) -> Self:
        """Construct a ConstraintViolationError from an asyncpg PostgresError."""
        return cls(
            table=getattr(e, "table_name", None),
            constraint=getattr(e, "constraint_name", None),
        )
