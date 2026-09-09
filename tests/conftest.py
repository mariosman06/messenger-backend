import logging
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer

from src.database.connection import close_pool, get_conn, init_pool
from src.database.queries import clear_tables, ensure_indexes_exist, ensure_tables_exist
from src.main import app
from tests.factories import TestUser, UserFactory

logging.raiseExceptions = False


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as postgres:
        yield postgres


@pytest.fixture(scope="session", autouse=True)
async def initialize_db(postgres_container):
    """Starts the database connection pool before tests run and closes it after."""
    dsn = postgres_container.get_connection_url().replace("postgresql+psycopg2", "postgresql")

    await init_pool(dsn=dsn)
    async with get_conn() as conn:
        await ensure_tables_exist(conn)
        await ensure_indexes_exist(conn)
    yield
    await close_pool()


@pytest.fixture(scope="function", autouse=True)
async def clear_db_between_tests():
    """Truncates all tables before each test execution."""
    async with get_conn() as conn:
        await clear_tables(conn)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Provides an HTTPX AsyncClient for driving FastAPI endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_factory() -> Callable[..., Awaitable[TestUser]]:
    """Fixture providing factory access to create users inside tests."""
    return UserFactory.create
