"""Redis Pub/Sub message publishing and async channel listener utilities."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis

from src.utils.tasks import spawn_task

from .errors import handle_redis_errors

logger = logging.getLogger(__name__)


@handle_redis_errors
async def publish_ws_push(client: redis.Redis, channel: str, payload: dict[str, Any]) -> None:
    """Serializes and publishes a JSON payload to a specified Redis channel."""
    await client.publish(channel, json.dumps(payload))


async def _safe_dispatch(
    message_handler: Callable[[dict[str, Any]], Awaitable[Any]],
    payload: dict[str, Any],
    channel: str,
) -> None:
    """Executes message handler in an isolated background task to prevent blocking the listener loop."""
    try:
        await message_handler(payload)
    except Exception as e:
        logger.error("Message handler failed on channel %s: %s", channel, e)


async def listen_and_dispatch_message(
    client: redis.Redis,
    channel: str,
    message_handler: Callable[[dict[str, Any]], Awaitable[Any]],
    *,
    close_client_on_exit: bool = False,
) -> None:
    """Subscribes to a Redis channel and continuously dispatches received messages with auto-recovery."""
    try:
        while True:
            try:
                pubsub = client.pubsub()
                await pubsub.subscribe(channel)
                logger.info("Subscribed to Redis channel: %s", channel)

                try:
                    async for msg in pubsub.listen():
                        if msg["type"] == "message":
                            try:
                                raw_data = msg["data"]
                                data = (
                                    raw_data.decode()
                                    if isinstance(raw_data, bytes)
                                    else raw_data
                                )
                                payload = json.loads(data)

                                # Uses spawn_task for GC protection + instant non-blocking dispatch
                                spawn_task(_safe_dispatch(message_handler, payload, channel))

                            except json.JSONDecodeError as e:
                                logger.error("Malformed JSON on channel %s: %s", channel, e)
                finally:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()

            except asyncio.CancelledError:
                logger.info("PubSub listener for %s cancelled.", channel)
                raise
            except Exception as e:
                logger.error(
                    "Redis PubSub listener for %s dropped: %s. Reconnecting in 2s...",
                    channel,
                    e,
                )
                await asyncio.sleep(2.0)
    finally:
        if close_client_on_exit:
            await client.aclose()
