"""Redis exceptions and driver error translation utilities."""

import functools
from collections.abc import Callable
from typing import Any

import redis.exceptions


class RedisError(Exception):
    """Base exception for all Redis operations."""

    def __init__(self, message: str = "An unexpected Redis error occurred."):
        super().__init__(message)


class RedisClientNotInitializedError(RedisError, RuntimeError):
    """Raised when an operation requires an active client that has not been initialized."""

    def __init__(
        self,
        message: str = "The Redis client has not been initialized.",
    ):
        super().__init__(message)


class RedisConnectionError(RedisError):
    """Raised when connection to Redis drops or fails to establish."""

    def __init__(self, message: str = "Could not establish connection to Redis."):
        super().__init__(message)


class RedisTimeoutError(RedisError):
    """Raised when a Redis operation times out."""

    def __init__(self, message: str = "The Redis operation timed out."):
        super().__init__(message)


class RedisCommandError(RedisError):
    """Raised when a Redis command fails execution."""

    def __init__(self, message: str = "Redis command execution failed."):
        super().__init__(message)


def handle_redis_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator mapping native redis-py exceptions to domain exceptions."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except redis.exceptions.TimeoutError as e:
            raise RedisTimeoutError(
                f"Redis operation timed out in {func.__name__}: {e}"
            ) from e
        except redis.exceptions.ConnectionError as e:
            raise RedisConnectionError(
                f"Redis connection failed in {func.__name__}: {e}"
            ) from e
        except redis.exceptions.RedisError as e:
            raise RedisCommandError(f"Redis command failed in {func.__name__}: {e}") from e

    return wrapper
