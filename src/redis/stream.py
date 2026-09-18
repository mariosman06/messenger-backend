"""Redis Streams utilities for guaranteed delivery of system events (e.g., Cache Invalidation)."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .connection import get_redis
from .errors import handle_redis_errors
from .events import RedisEvent

logger = logging.getLogger(__name__)

# System stream configurations
SYSTEM_STREAM_KEY = "system_events_stream"
MAX_STREAM_LENGTH = 10000


@handle_redis_errors
async def publish_stream_event(
    event: RedisEvent, stream_name: str = SYSTEM_STREAM_KEY
) -> None:
    """Serializes and pushes a strongly-typed event JSON payload to a Redis Stream."""
    client = get_redis()
    json_payload = json.dumps(event.to_dict())

    await client.xadd(
        stream_name,
        {"payload": json_payload},
        maxlen=MAX_STREAM_LENGTH,
    )


async def listen_to_stream(
    message_handler: Callable[[dict[str, Any]], Awaitable[None]],
    stream_name: str = SYSTEM_STREAM_KEY,
) -> None:
    """Listens to a Redis Stream with a local cursor to guarantee delivery even after disconnects."""
    client = get_redis()
    last_id: str | bytes = "$"

    logger.info("Starting Redis Stream listener for: %s", stream_name)

    while True:
        try:
            # Block up to 2 seconds waiting for new items, then yield loop control
            streams = await client.xread({stream_name: last_id}, block=2000)

            # Type Guard: Assures type checker that 'streams' is iterable (a list)
            if isinstance(streams, list):
                for _stream, messages in streams:
                    # Type Guard: Assures type checker that 'messages' is iterable
                    if isinstance(messages, list):
                        for message_id, message_data in messages:
                            try:
                                # Extract and decode the JSON payload safely
                                raw_payload = message_data.get(b"payload")
                                if raw_payload:
                                    payload_str = (
                                        raw_payload.decode()
                                        if isinstance(raw_payload, bytes)
                                        else raw_payload
                                    )
                                    event_dict = json.loads(payload_str)

                                    # Dispatch to the worker's internal cache-clear handler
                                    await message_handler(event_dict)

                            except Exception as e:
                                logger.error(
                                    "Failed processing stream payload %s: %s", message_id, e
                                )

                            # Advance cursor locally so we don't re-process this on disconnect
                            last_id = message_id

        except Exception as e:
            logger.error("Redis Stream listener dropped: %s. Reconnecting in 2s...", e)
            await asyncio.sleep(2.0)
