"""API dependencies for authentication, token extraction, and service resolution."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

import src.database.queries as db_queries
from src.crypto.tokens import hash_token
from src.database.connection import DatabaseManager
from src.database.errors import NotFoundError
from src.database.models import User
from src.services.auth import AuthService, TokenCache
from src.services.group import GroupService
from src.services.messaging import MessagingService
from src.services.user import UserService
from src.services.websocket import WebSocketManager

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


# HTTP infrastructure extractors from app.state
def get_db(request: Request) -> DatabaseManager:
    """Retrieves DatabaseManager instance from app state."""
    return request.app.state.db


def get_redis(request: Request) -> Redis:
    """Retrieves active Redis client instance from app state."""
    return request.app.state.redis.client


def get_ws_manager(request: Request) -> WebSocketManager:
    """Retrieves WebSocketManager instance from app state."""
    return request.app.state.ws_manager


def get_token_cache(request: Request) -> TokenCache:
    """Retrieves worker-local TokenCache instance from app state."""
    return request.app.state.auth_cache


# WebSocket infrastructure extractors from app.state
def get_db_ws(websocket: WebSocket) -> DatabaseManager:
    """Retrieves DatabaseManager instance from WebSocket app state."""
    return websocket.app.state.db


def get_token_cache_ws(websocket: WebSocket) -> TokenCache:
    """Retrieves worker-local TokenCache instance from WebSocket app state."""
    return websocket.app.state.auth_cache


def get_ws_manager_ws(websocket: WebSocket) -> WebSocketManager:
    """Retrieves WebSocketManager instance from WebSocket app state."""
    return websocket.app.state.ws_manager


# Token extraction helper
def get_raw_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str | None:
    """Extracts the raw bearer token string if present."""
    return credentials.credentials if credentials else None


# Core token validation checking L1 RAM first, then L2 Postgres
async def authenticate_token(
    raw_token: str,
    db: DatabaseManager,
    cache: TokenCache,
    allow_deactivated: bool = False,
) -> User:
    """Validates raw token by checking L1 RAM first, then falling back to L2 Postgres."""
    token_hash = hash_token(raw_token)

    # Fast path: check worker-local RAM cache first
    cached_user = cache.get(token_hash)
    if cached_user is not None:
        if cached_user.deactivated and not allow_deactivated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return cached_user

    # Slow path: query PostgreSQL
    try:
        async with db.connection() as conn:
            token_record = await db_queries.get_access_token(conn, token_hash)

            if token_record.is_revoked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access token has been revoked.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if token_record.is_expired:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Access token has expired.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            user = await db_queries.get_user_by_id(conn, token_record.user_id)

            if user.deactivated and not allow_deactivated:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User account is deactivated.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or nonexistent access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    # Store in RAM cache for subsequent lookups
    cache.set(token_hash, user)
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[DatabaseManager, Depends(get_db)],
    cache: Annotated[TokenCache, Depends(get_token_cache)],
) -> User:
    """Resolves active authenticated user from the HTTP Bearer header."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await authenticate_token(credentials.credentials, db, cache)


async def get_current_user_allow_deactivated(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[DatabaseManager, Depends(get_db)],
    cache: Annotated[TokenCache, Depends(get_token_cache)],
) -> User:
    """Resolves authenticated user allowing deactivated accounts (used for reactivation)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await authenticate_token(credentials.credentials, db, cache, allow_deactivated=True)


async def get_current_user_ws(
    websocket: WebSocket,
    token: Annotated[str | None, Query()] = None,
    db: DatabaseManager = Depends(get_db_ws),
    cache: TokenCache = Depends(get_token_cache_ws),
) -> User:
    """Resolves authenticated user from WebSocket query parameter."""
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing WebSocket authentication token query parameter.",
        )
    try:
        return await authenticate_token(token, db, cache)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise


# Service factory dependencies
def get_auth_service(
    db: Annotated[DatabaseManager, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    cache: Annotated[TokenCache, Depends(get_token_cache)],
) -> AuthService:
    """Instantiates AuthService with injected dependencies."""
    return AuthService(db=db, redis=redis, cache=cache)


def get_user_service(
    db: Annotated[DatabaseManager, Depends(get_db)],
) -> UserService:
    """Instantiates UserService with injected DatabaseManager."""
    return UserService(db=db)


def get_messaging_service(
    db: Annotated[DatabaseManager, Depends(get_db)],
    ws_manager: Annotated[WebSocketManager, Depends(get_ws_manager)],
) -> MessagingService:
    """Instantiates MessagingService with injected dependencies."""
    return MessagingService(db=db, ws_manager=ws_manager)


def get_group_service(
    db: Annotated[DatabaseManager, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    ws_manager: Annotated[WebSocketManager, Depends(get_ws_manager)],
) -> GroupService:
    """Instantiates GroupService with injected dependencies."""
    return GroupService(db=db, redis=redis, ws_manager=ws_manager)


# Route dependency type aliases
CurrentUser = Annotated[User, Depends(get_current_user)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
MessagingServiceDep = Annotated[MessagingService, Depends(get_messaging_service)]
GroupServiceDep = Annotated[GroupService, Depends(get_group_service)]
WebSocketManagerDep = Annotated[WebSocketManager, Depends(get_ws_manager)]
