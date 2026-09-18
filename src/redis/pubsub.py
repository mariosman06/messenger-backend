"""Redis Pub/Sub message publishing and async channel listener utilities."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .connection import get_redis
from .errors import handle_redis_errors

logger = logging.getLogger(__name__)


@handle_redis_errors
async def publish_ws_push(channel: str, payload: dict[str, Any]) -> None:
    """Serializes and publishes a JSON payload to a specified Redis channel."""
    client = get_redis()
    await client.publish(channel, json.dumps(payload))


async def listen_and_dispatch_message(
    channel: str, message_handler: Callable[[dict[str, Any]], Awaitable[Any]]
) -> None:
    """Subscribes to a Redis channel and continuously dispatches received messages with auto-recovery."""
    client = get_redis()

    # 1. Outer loop guarantees the listener always restarts if Redis disconnects
    while True:
        try:
            pubsub = client.pubsub()
            await pubsub.subscribe(channel)
            logger.info("Subscribed to Redis channel: %s", channel)

            try:
                async for msg in pubsub.listen():
                    if msg["type"] == "message":
                        # 2. Inner try/except guarantees bad payloads don't kill the listener
                        try:
                            # Handle byte decoding depending on redis-py config
                            data = (
                                msg["data"].decode()
                                if isinstance(msg["data"], bytes)
                                else msg["data"]
                            )
                            payload = json.loads(data)
                            await message_handler(payload)
                        except json.JSONDecodeError as e:
                            logger.error(
                                "Malformed JSON received on channel %s: %s", channel, e
                            )
                        except Exception as e:
                            logger.error(
                                "Message handler failed on channel %s: %s", channel, e
                            )
            finally:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()

        except Exception as e:
            logger.error(
                "Redis PubSub listener for %s disconnected: %s. Reconnecting...", channel, e
            )
            await asyncio.sleep(2.0)  # Backoff to prevent spamming reconnection attempts
