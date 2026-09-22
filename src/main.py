"""FastAPI application setup, explicit lifespan lifecycles, and global error handlers."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers.auth import router as auth_router
from src.api.routers.group import router as groups_router
from src.api.routers.messaging import router as messages_router
from src.api.routers.user import router as users_router
from src.api.routers.websocket import router as websockets_router
from src.config.logging import request_id_var, setup_logging
from src.config.settings import get_settings
from src.database.connection import DatabaseManager
from src.database.errors import DatabaseError
from src.database.queries import ensure_indexes_exist, ensure_tables_exist
from src.redis.connection import RedisManager
from src.redis.errors import RedisError
from src.redis.stream import listen_to_stream
from src.services.auth import TokenCache
from src.services.errors import ServiceError
from src.services.websocket import WebSocketManager
from src.utils.generators import uuid_v4

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
logger.info(f"Loaded settings: {settings.model_dump()} for environment.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Manages application startup, dependency orchestration, and graceful shutdown."""
    # Initialize PostgreSQL pool
    db_manager = DatabaseManager(
        dsn=settings.database.dsn,
        min_size=settings.database.min_pool_size,
        max_size=settings.database.max_pool_size,
    )
    await db_manager.connect()

    # Ensure schema and indexes exist
    async with db_manager.connection() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('messenger_schema_init'));")
        logger.info("Running database initialization and schema setup...")
        await ensure_tables_exist(conn=conn)
        await ensure_indexes_exist(conn=conn)
        logger.info("Database schema is up to date.")

    # Initialize Redis client and connection pool
    redis_manager = RedisManager(
        url=settings.redis.url,
        max_connections=settings.redis.max_connections,
    )
    await redis_manager.connect()

    # Initialize worker-local token cache and WebSocket manager
    auth_cache = TokenCache()
    ws_manager = WebSocketManager(db=db_manager, redis=redis_manager.client)

    # Attach instances to app.state for dependency injection
    app.state.db = db_manager
    app.state.redis = redis_manager
    app.state.auth_cache = auth_cache
    app.state.ws_manager = ws_manager

    # Start background listeners
    pubsub_task = ws_manager.start_pubsub_listener()
    stream_task = asyncio.create_task(
        listen_to_stream(
            client=redis_manager.client,
            message_handler=auth_cache.handle_invalidation_event,
        )
    )

    yield

    # Graceful shutdown: cancel background workers
    logger.info("Cancelling background listeners...")
    pubsub_task.cancel()
    stream_task.cancel()
    try:
        await asyncio.gather(pubsub_task, stream_task)
    except asyncio.CancelledError:
        pass

    # Teardown Redis connections
    logger.info("Closing Redis connections...")
    await redis_manager.disconnect()

    # Teardown database connection pool
    logger.info("Closing database connection pool...")
    await db_manager.disconnect()


# Set default_response_class to ORJSONResponse for high-performance serialization
app = FastAPI(
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Correlates requests with an X-Request-ID and measures execution latency."""
    req_id = request.headers.get("X-Request-ID") or str(uuid_v4())[:8]
    token = request_id_var.set(req_id)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        process_time = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s - %s (%.2fms)",
            request.method,
            request.url.path,
            response.status_code,
            process_time,
        )
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        request_id_var.reset(token)


# Exception Handlers updated to ORJSONResponse
@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    logger.warning("Domain logic error: %s", exc)
    status_code = getattr(exc, "status_code", status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc)},
    )


@app.exception_handler(DatabaseError)
async def database_error_handler(request: Request, exc: DatabaseError) -> JSONResponse:
    logger.error("Database execution error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "A database operation failed."},
    )


@app.exception_handler(RedisError)
async def redis_error_handler(request: Request, exc: RedisError) -> JSONResponse:
    logger.error("Redis execution error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "A caching or messaging operation failed."},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred."},
    )


# Routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(groups_router)
app.include_router(messages_router)
app.include_router(websockets_router)
