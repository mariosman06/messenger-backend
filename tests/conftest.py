"""Global pytest fixtures and test container lifecycle configuration."""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

import pytest
import yaml
from fastapi.websockets import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from src.database.connection import DatabaseManager
from src.database.queries import clear_tables, ensure_indexes_exist, ensure_tables_exist
from src.main import app
from src.redis.connection import RedisManager
from src.redis.stream import listen_to_stream
from src.services.auth import TokenCache
from src.services.websocket import WebSocketManager
from tests.factories import TestUser, UserFactory

logging.raiseExceptions = False

NOISY_LOGGERS = [
    "httpcore",
    "httpx",
    "websockets",
    "asyncio",
    "uvicorn",
    "urllib3",
    "docker",
    "testcontainers",
]
for logger_name in NOISY_LOGGERS:
    logging.getLogger(logger_name).setLevel(logging.WARNING)


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
    """Starts a PostgreSQL test container for the duration of the test session."""
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def redis_container():
    """Starts a Redis test container for the duration of the test session."""
    with RedisContainer("redis:7-alpine") as redis:
        yield redis


@pytest.fixture(scope="session", autouse=True)
async def initialize_infrastructure(postgres_container, redis_container):
    """Initializes DatabaseManager, RedisManager, and services for in-process tests."""
    postgres_dsn = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2", "postgresql"
    )
    redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}/0"

    # Instantiate managers with test container endpoints
    db_manager = DatabaseManager(dsn=postgres_dsn, min_size=2, max_size=10)
    await db_manager.connect()

    redis_manager = RedisManager(url=redis_url, max_connections=20)
    await redis_manager.connect()

    auth_cache = TokenCache()
    ws_manager = WebSocketManager(db=db_manager, redis=redis_manager.client)

    # Attach to app.state for in-process ASGI clients
    app.state.db = db_manager
    app.state.redis = redis_manager
    app.state.auth_cache = auth_cache
    app.state.ws_manager = ws_manager

    # Initialize schema and indexes
    async with db_manager.connection() as conn:
        await ensure_tables_exist(conn)
        await ensure_indexes_exist(conn)

    # Start background listeners
    pubsub_task = ws_manager.start_pubsub_listener()
    stream_task = asyncio.create_task(
        listen_to_stream(
            client=redis_manager.client,
            message_handler=auth_cache.handle_invalidation_event,
        )
    )

    yield

    # Teardown background tasks
    pubsub_task.cancel()
    stream_task.cancel()
    try:
        await asyncio.gather(pubsub_task, stream_task)
    except asyncio.CancelledError:
        pass

    # Teardown connection pools
    await redis_manager.disconnect()
    await db_manager.disconnect()


@pytest.fixture(scope="function", autouse=True)
async def clear_state_between_tests():
    """Truncates DB tables, flushes Redis keys, and clears RAM cache between tests."""
    async with app.state.db.connection() as conn:
        await clear_tables(conn)

    await app.state.redis.client.flushdb()
    app.state.auth_cache.clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Provides an HTTPX AsyncClient for driving FastAPI endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_factory() -> Callable[..., Awaitable[TestUser]]:
    """Fixture providing factory access to create users inside tests."""
    return UserFactory.create


@pytest.fixture(scope="session")
def multi_worker_server(postgres_container, redis_container):
    """Spawns a live Uvicorn multi-worker process pointing to active Testcontainers."""
    pg_host = postgres_container.get_container_host_ip()
    pg_port = postgres_container.get_exposed_port(5432)
    pg_user = postgres_container.username
    pg_password = postgres_container.password
    pg_db = postgres_container.dbname

    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    redis_url = f"redis://{redis_host}:{redis_port}/0"

    test_config = {
        "logging": {"level": "INFO"},
        "database": {
            "host": pg_host,
            "port": pg_port,
            "user": pg_user,
            "password": pg_password,
            "database": pg_db,
        },
        "auth": {
            "access_token_ttl": 900,
            "refresh_token_ttl": 604800,
        },
        "redis": {
            "url": redis_url,
        },
    }

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tmp_file:
        yaml.dump(test_config, tmp_file)
        tmp_config_path = tmp_file.name

    env = os.environ.copy()
    env["APP_CONFIG_PATH"] = tmp_config_path

    # Set stdout and stderr to None so child Uvicorn logs stream directly to the terminal
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8888",
            "--workers",
            "4",
        ],
        env=env,
        stdout=None,
        stderr=None,
        text=True,
    )

    start_time = time.time()
    connected = False
    while time.time() - start_time < 15:
        if proc.poll() is not None:
            os.unlink(tmp_config_path)
            raise RuntimeError("Uvicorn multi-worker process failed to start.")
        try:
            with socket.create_connection(("127.0.0.1", 8888), timeout=0.5):
                connected = True
                break
        except (OSError, ConnectionRefusedError):
            time.sleep(0.2)

    if not connected:
        proc.kill()
        os.unlink(tmp_config_path)
        raise RuntimeError("Uvicorn server timed out starting on port 8888.")

    yield "http://127.0.0.1:8888"

    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()

    if os.path.exists(tmp_config_path):
        os.unlink(tmp_config_path)
