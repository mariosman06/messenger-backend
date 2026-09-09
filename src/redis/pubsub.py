"""Redis Pub/Sub message publishing and async channel listener utilities."""

import json
from collections.abc import Callable
from typing import Any

from .connection import get_redis
from .errors import handle_redis_errors


@handle_redis_errors
async def publish_ws_push(channel: str, payload: dict) -> None:
    """Serializes and publishes a JSON payload to a specified Redis channel."""
    client = get_redis()
    await client.publish(channel, json.dumps(payload))


@handle_redis_errors
async def listen_and_dispatch_message(
    channel: str, message_handler: Callable[[dict], Any]
) -> None:
    """Subscribes to a Redis channel and continuously dispatches received messages to a handler."""
    client = get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)

    try:
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                payload = json.loads(msg["data"])
                await message_handler(payload)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
