"""FastAPI app setup, DB pool lifecycle, logging setup, and global error handlers."""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers.auth import router as auth_router
from src.api.routers.friendships import router as friendships_router
from src.api.routers.groups import router as groups_router
from src.api.routers.messages import router as messages_router
from src.api.routers.users import router as users_router
from src.config.logging import request_id_var, setup_logging
from src.config.settings import get_settings
from src.database.connection import close_pool, get_conn, init_pool
from src.database.errors import DatabaseError
from src.database.queries import ensure_indexes_exist, ensure_tables_exist
from src.services.errors import ServiceError
from src.utils.generators import uuid_v4

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()
logger.info(f"loaded settings: {settings.model_dump()}.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    pool = await init_pool(dsn=settings.database.dsn)

    async with get_conn(pool=pool) as conn:
        logger.info("Running database initialization and schema setup...")
        await ensure_tables_exist(conn=conn)
        await ensure_indexes_exist(conn=conn)
        logger.info("Database schema is up to date.")

    yield

    logger.info("Closing database connection pool...")
    await close_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid_v4())[:8]
    token = request_id_var.set(req_id)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        process_time = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code} ({process_time:.2f}ms)"
        )
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        request_id_var.reset(token)


# Exception Handlers


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
app.include_router(friendships_router)
app.include_router(groups_router)
app.include_router(messages_router)
