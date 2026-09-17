import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task[Any]] = set()


def spawn_task(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Spawns a fire-and-forget background task safely with GC protection and logging."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)

    def _handle_completion(t: asyncio.Task[Any]) -> None:
        _background_tasks.discard(t)
        if not t.cancelled() and (exc := t.exception()):
            logger.error("Unhandled exception in background task: %s", exc, exc_info=exc)

    task.add_done_callback(_handle_completion)
    return task


async def drain_background_tasks(timeout_seconds: float = 5.0) -> None:
    """Flushes active background tasks on application shutdown."""
    if not _background_tasks:
        return

    logger.info("Flushing %d pending background task(s)...", len(_background_tasks))
    _, pending = await asyncio.wait(_background_tasks, timeout=timeout_seconds)

    for task in pending:
        task.cancel()
        logger.warning("Cancelled timed-out background task on shutdown.")
