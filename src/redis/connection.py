"""Redis connection lifecycle management and client encapsulation."""

import logging

from redis.asyncio import BlockingConnectionPool, Redis
from redis.asyncio.client import PubSub

from .errors import RedisClientNotInitializedError, handle_redis_errors

logger = logging.getLogger(__name__)


class RedisManager:
    """Manages Redis connection pooling and client lifecycles."""

    def __init__(
        self,
        url: str,
        max_connections: int = 200,
        decode_responses: bool = True,
        timeout: float = 10.0,
        socket_timeout: float = 5.0,
    ) -> None:
        self._url = url
        self._max_connections = max_connections
        self._decode_responses = decode_responses
        self._timeout = timeout
        self._socket_timeout = socket_timeout
        self._pool: BlockingConnectionPool | None = None
        self._client: Redis | None = None

    @handle_redis_errors
    async def connect(self) -> Redis:
        """Initializes blocking connection pool, validates connection with ping, and returns client."""
        if self._client is not None:
            logger.debug("Redis client already initialized.")
            return self._client

        logger.info("Initializing Redis connection pool targeting %s", self._url)
        # BlockingConnectionPool queues requests when full instead of throwing MaxConnectionsError immediately
        self._pool = BlockingConnectionPool.from_url(
            self._url,
            decode_responses=self._decode_responses,
            max_connections=self._max_connections,
            timeout=self._timeout,
            socket_timeout=self._socket_timeout,
            socket_connect_timeout=self._socket_timeout,
            health_check_interval=30,
        )
        self._client = Redis(connection_pool=self._pool)

        await self._client.ping()
        logger.info("Redis connection pool established successfully.")
        return self._client

    async def disconnect(self) -> None:
        """Gracefully closes active Redis client sessions and tears down pool."""
        logger.info("Closing Redis connection pool and client...")
        try:
            if self._client:
                await self._client.aclose()
                self._client = None
            if self._pool:
                await self._pool.aclose()
                self._pool = None
            logger.info("Redis connection pool and client closed successfully.")
        except Exception as e:
            logger.warning("Error encountered during Redis disconnect: %s", e)

    @property
    def client(self) -> Redis:
        """Retrieves the initialized Redis client instance."""
        if self._client is None:
            logger.error("Attempted to access uninitialized Redis client.")
            raise RedisClientNotInitializedError()
        return self._client

    def pubsub(self) -> PubSub:
        """Spawns a dedicated async PubSub instance from the pool."""
        return self.client.pubsub()
