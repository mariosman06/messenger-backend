"""Global pytest fixtures and test container lifecycle configuration."""

import asyncio
import json
import logging
import urllib.parse
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
from fastapi.websockets import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from src.database.connection import close_pool, get_conn, init_pool
from src.database.queries import clear_tables, ensure_indexes_exist, ensure_tables_exist
from src.main import app
from src.redis.connection import close_redis, get_redis, init_redis
from tests.factories import TestUser, UserFactory

logging.raiseExceptions = False


class AsyncWebSocketSession:
    """Async WebSocket test session running directly on the test asyncio loop."""

    def __init__(
        self, req_queue: asyncio.Queue, resp_queue: asyncio.Queue, task: asyncio.Task
    ):
        self._req_queue = req_queue
        self._resp_queue = resp_queue
        self._task = task

    async def send_json(self, data: dict) -> None:
        await self._req_queue.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def receive_json(self) -> dict:
        msg = await self._resp_queue.get()
        if msg["type"] == "websocket.close":
            raise WebSocketDisconnect(code=msg.get("code", 1000), reason=msg.get("reason", ""))
        if msg["type"] == "websocket.send":
            if "text" in msg and msg["text"] is not None:
                return json.loads(msg["text"])
            if "bytes" in msg and msg["bytes"] is not None:
                return json.loads(msg["bytes"].decode("utf-8"))
        raise RuntimeError(f"Unexpected ASGI message type: {msg['type']}")

    async def close(self, code: int = 1000) -> None:
        await self._req_queue.put({"type": "websocket.disconnect", "code": code})


@asynccontextmanager
async def websocket_connect(path: str):
    """Connects to ASGI WebSocket endpoint asynchronously on the current asyncio event loop."""
    parsed = urllib.parse.urlparse(path)
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0"},
        "scheme": "ws",
        "path": parsed.path,
        "raw_path": parsed.path.encode("utf-8"),
        "query_string": parsed.query.encode("utf-8"),
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "subprotocols": [],
    }

    req_queue: asyncio.Queue = asyncio.Queue()
    resp_queue: asyncio.Queue = asyncio.Queue()

    async def receive():
        return await req_queue.get()

    async def send(message):
        await resp_queue.put(message)

    app_task = asyncio.create_task(app(scope, receive, send))
    await req_queue.put({"type": "websocket.connect"})

    try:
        connect_msg = await resp_queue.get()
    except Exception:
        app_task.cancel()
        raise

    if connect_msg["type"] == "websocket.close":
        app_task.cancel()
        raise WebSocketDisconnect(
            code=connect_msg.get("code", 1000), reason=connect_msg.get("reason", "")
        )
    elif connect_msg["type"] in (
        "websocket.http.response.start",
        "websocket.http.response.body",
    ):
        app_task.cancel()
        raise WebSocketDisconnect(code=4003, reason="Connection rejected by server")
    elif connect_msg["type"] != "websocket.accept":
        app_task.cancel()
        raise RuntimeError(f"Unexpected ASGI response: {connect_msg}")

    session = AsyncWebSocketSession(req_queue, resp_queue, app_task)
    try:
        yield session
    finally:
        await session.close()
        try:
            await asyncio.wait_for(app_task, timeout=0.2)
        except (TimeoutError, asyncio.CancelledError):
            app_task.cancel()


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session", autouse=True)
async def initialize_infrastructure(postgres_container, redis_container):
    """Initializes PostgreSQL pool and Redis client for the test session."""
    postgres_dsn = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql"
    )
    redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}/0"

    await init_pool(dsn=postgres_dsn)
    await init_redis(url=redis_url)

    async with get_conn() as conn:
        await ensure_tables_exist(conn)
        await ensure_indexes_exist(conn)

    yield

    await close_redis()
    await close_pool()


@pytest.fixture(scope="function", autouse=True)
async def clear_state_between_tests():
    """Truncates DB tables and flushes Redis keys between each test."""
    async with get_conn() as conn:
        await clear_tables(conn)

    redis_client = get_redis()
    await redis_client.flushdb()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Provides an HTTPX AsyncClient for driving FastAPI endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_factory() -> Callable[..., Awaitable[TestUser]]:
    """Fixture providing factory access to create users inside tests."""
    return UserFactory.create
