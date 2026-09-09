"""Authentication API router handling user registration, login, token refresh, profile retrieval, and logout."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

import src.services.auth as auth_service
from src.api.dependencies import get_current_user, get_raw_access_token
from src.api.schemas import (
    AuthResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserResponse,
)
from src.database.models import User

router = APIRouter(prefix="/auth", tags=["Auth"])


# Auth Endpoints


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: RegisterRequest) -> AuthResponse:
    """Registers a new user account and issues an initial token pair."""
    u, t = await auth_service.register(username=payload.username, password=payload.password)
    return AuthResponse(
        user=UserResponse.model_validate(u), tokens=TokenPairResponse.model_validate(t)
    )


@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user credentials",
)
async def login(payload: LoginRequest) -> AuthResponse:
    """Authenticates user credentials and returns a fresh token pair."""
    u, t = await auth_service.login(username=payload.username, password=payload.password)
    return AuthResponse(
        user=UserResponse.model_validate(u), tokens=TokenPairResponse.model_validate(t)
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh authentication tokens",
)
async def refresh(payload: RefreshRequest) -> TokenPairResponse:
    """Rotates an existing refresh token and returns a new token pair."""
    return TokenPairResponse.model_validate(
        await auth_service.refresh(raw_refresh_token=payload.refresh_token)
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> UserResponse:
    """Retrieves the authenticated user's profile information."""
    return UserResponse.model_validate(current_user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout user session",
)
async def logout(
    payload: LogoutRequest,
    raw_access_token: Annotated[str | None, Depends(get_raw_access_token)],
) -> None:
    """Revokes refresh and optional access tokens to terminate the user session."""
    await auth_service.logout(
        raw_refresh_token=payload.refresh_token, raw_access_token=raw_access_token
    )
