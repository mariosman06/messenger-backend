"""API dependencies for authentication, token extraction, and user context resolution."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.crypto.tokens import hash_token
from src.database.connection import get_conn
from src.database.errors import NotFoundError
from src.database.models import User
from src.database.queries import get_access_token, get_user_by_id

# Security Schemes


bearer_scheme = HTTPBearer(auto_error=False)


# Token Extractors


async def get_raw_access_token(
    auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str | None:
    """Extracts the raw bearer token string from the HTTP Authorization header if present."""
    return auth.credentials if auth else None


# Authentication Dependencies


async def _resolve_current_user(
    raw_token: Annotated[str | None, Depends(get_raw_access_token)],
    allow_deactivated: bool = False,
) -> User:
    """Validates the access token state and resolves the authenticated user context."""
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_hash = hash_token(raw_token)

    async with get_conn() as conn:
        try:
            token_record = await get_access_token(conn, token_hash)
        except NotFoundError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or unrecognized token.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

        if token_record.is_revoked or token_record.is_expired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired or revoked.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            user = await get_user_by_id(conn, token_record.user_id)
        except NotFoundError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account no longer exists.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

        if not allow_deactivated and user.deactivated:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User account is deactivated.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user


async def get_current_user(
    raw_token: Annotated[str | None, Depends(get_raw_access_token)],
) -> User:
    """Resolves authenticated context and blocks deactivated accounts."""
    return await _resolve_current_user(raw_token, allow_deactivated=False)


async def get_current_user_allow_deactivated(
    raw_token: Annotated[str | None, Depends(get_raw_access_token)],
) -> User:
    """Resolves authenticated context allowing deactivated users through for reactivation."""
    return await _resolve_current_user(raw_token, allow_deactivated=True)
