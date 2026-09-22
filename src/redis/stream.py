"""Redis Streams utilities for guaranteed delivery of system events (e.g., Cache Invalidation)."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis

from .errors import handle_redis_errors
from .events import RedisEvent

logger = logging.getLogger(__name__)

SYSTEM_STREAM_KEY = "system_events_stream"
MAX_STREAM_LENGTH = 10000


@handle_redis_errors
async def publish_stream_event(
    client: redis.Redis,
    event: RedisEvent,
    stream_name: str = SYSTEM_STREAM_KEY,
) -> None:
    """Serializes and pushes a strongly-typed event JSON payload to a Redis Stream."""
    json_payload = json.dumps(event.to_dict())
    await client.xadd(
        stream_name,
        {"payload": json_payload},
        maxlen=MAX_STREAM_LENGTH,
    )


async def listen_to_stream(
    client: redis.Redis,
    message_handler: Callable[[dict[str, Any]], Awaitable[None]],
    stream_name: str = SYSTEM_STREAM_KEY,
) -> None:
    """Listens to a Redis Stream with a local cursor to guarantee delivery even across disconnects."""
    last_id: str | bytes = "$"

    logger.info("Starting Redis Stream listener for: %s", stream_name)

    while True:
        try:
            streams = await client.xread({stream_name: last_id}, block=2000)

            if isinstance(streams, list):
                for _stream, messages in streams:
                    if isinstance(messages, list):
                        for message_id, message_data in messages:
                            try:
                                raw_payload = message_data.get("payload") or message_data.get(
                                    b"payload"
                                )

                                if raw_payload:
                                    payload_str = (
                                        raw_payload.decode()
                                        if isinstance(raw_payload, bytes)
                                        else raw_payload
                                    )
                                    event_dict = json.loads(payload_str)
                                    await message_handler(event_dict)

                            except Exception as e:
                                logger.error(
                                    "Failed processing stream payload %s: %s",
                                    message_id,
                                    e,
                                )

                            last_id = message_id

        except asyncio.CancelledError:
            logger.info("Redis Stream listener for %s cancelled.", stream_name)
            break
        except Exception as e:
            logger.error("Redis Stream listener dropped: %s. Reconnecting in 2s...", e)
            await asyncio.sleep(2.0)
