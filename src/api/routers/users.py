"""API endpoints for public user discovery, current user profile, and account lifecycle actions."""

from uuid import UUID

from fastapi import APIRouter, Depends, status

import src.services.users as users_service
from src.api.dependencies import get_current_user, get_current_user_allow_deactivated
from src.api.schemas import UserResponse
from src.database.models import User

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
) -> User:
    """Retrieves the authenticated user's own profile."""
    return current_user


@router.get("/by-username/{username}", response_model=UserResponse)
async def get_user_by_username(
    username: str,
    _current_user: User = Depends(get_current_user),
) -> User:
    """Looks up a user profile by username. Requires authentication."""
    return await users_service.get_by_username(username)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: UUID,
    _current_user: User = Depends(get_current_user),
) -> User:
    """Looks up a user profile by UUID. Requires authentication."""
    return await users_service.get_by_id(user_id)


@router.post("/me/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_my_account(
    current_user: User = Depends(get_current_user),
) -> None:
    """Deactivates the authenticated user's account."""
    await users_service.deactivate_account(current_user.user_id)


@router.post("/me/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_my_account(
    current_user: User = Depends(get_current_user_allow_deactivated),
) -> None:
    """Reactivates the authenticated user's account."""
    await users_service.reactivate_account(current_user.user_id)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently deletes the authenticated user's account."""
    await users_service.delete_account(current_user.user_id)
