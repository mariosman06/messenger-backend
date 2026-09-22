"""API endpoints for user profile discovery, account lifecycle actions, and social friendships."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.api.dependencies import (
    CurrentUser,
    UserServiceDep,
    get_current_user_allow_deactivated,
)
from src.api.schemas import FriendshipResponse, SendFriendRequest, UserResponse
from src.database.models import User

router = APIRouter(tags=["Users & Friendships"])


# Profile & Account Lifecycle Endpoints
@router.get("/users/me", response_model=UserResponse)
async def get_my_profile(current_user: CurrentUser) -> UserResponse:
    """Retrieves the authenticated user's own profile."""
    return UserResponse.model_validate(current_user)


@router.get("/users/by-username/{username}", response_model=UserResponse)
async def get_user_by_username(
    username: str,
    _current_user: CurrentUser,
    user_service: UserServiceDep,
) -> UserResponse:
    """Looks up a user profile by username. Requires authentication."""
    user = await user_service.get_by_username(username)
    return UserResponse.model_validate(user)


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user_by_id(
    user_id: UUID,
    _current_user: CurrentUser,
    user_service: UserServiceDep,
) -> UserResponse:
    """Looks up a user profile by primary key. Requires authentication."""
    user = await user_service.get_by_id(user_id)
    return UserResponse.model_validate(user)


@router.post("/users/me/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_my_account(
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> None:
    """Deactivates the authenticated user's account."""
    await user_service.deactivate_account(current_user.user_id)


@router.post("/users/me/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_my_account(
    current_user: Annotated[User, Depends(get_current_user_allow_deactivated)],
    user_service: UserServiceDep,
) -> None:
    """Reactivates the authenticated user's account."""
    await user_service.reactivate_account(current_user.user_id)


@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> None:
    """Permanently deletes the authenticated user's account."""
    await user_service.delete_account(current_user.user_id)


# Friendship & Request Endpoints
@router.post(
    "/friends/requests",
    status_code=status.HTTP_201_CREATED,
    summary="Send a friend request",
)
async def send_request(
    payload: SendFriendRequest,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> dict[str, str]:
    """Dispatches a new pending friend request to a target user."""
    await user_service.send_friend_request(
        requester_id=current_user.user_id, addressee_id=payload.addressee_id
    )
    return {"message": "Friend request sent successfully."}


@router.get(
    "/friends/requests/pending",
    response_model=list[FriendshipResponse],
    status_code=status.HTTP_200_OK,
    summary="List pending incoming friend requests",
)
async def list_pending_requests(
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> list[FriendshipResponse]:
    """Retrieves all incoming pending friend requests awaiting action."""
    pending = await user_service.get_pending_friend_requests(user_id=current_user.user_id)
    return [FriendshipResponse.model_validate(p) for p in pending]


@router.post(
    "/friends/requests/{requester_id}/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept a pending friend request",
)
async def accept_request(
    requester_id: UUID,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> dict[str, str]:
    """Accepts an incoming pending friend request."""
    await user_service.accept_friend_request(
        addressee_id=current_user.user_id, requester_id=requester_id
    )
    return {"message": "Friend request accepted."}


@router.get(
    "/friends",
    response_model=list[FriendshipResponse],
    status_code=status.HTTP_200_OK,
    summary="List all accepted friends",
)
async def list_friends(
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> list[FriendshipResponse]:
    """Retrieves all active, accepted friendships for the calling user."""
    friends = await user_service.get_friends(user_id=current_user.user_id)
    return [FriendshipResponse.model_validate(f) for f in friends]


@router.get(
    "/friends/{target_id}/status",
    response_model=FriendshipResponse,
    status_code=status.HTTP_200_OK,
    summary="Get friendship status with a specific user",
)
async def get_status(
    target_id: UUID,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> FriendshipResponse:
    """Fetches the friendship record establishing relationship status with a user."""
    status_record = await user_service.get_friendship_status(
        user_a=current_user.user_id, user_b=target_id
    )
    return FriendshipResponse.model_validate(status_record)


@router.delete(
    "/friends/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a friend, cancel a request, or decline a request",
)
async def remove_or_decline(
    target_id: UUID,
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> None:
    """Terminates an existing friendship or cancels/declines an active request."""
    await user_service.remove_or_decline_friendship(
        user_a=current_user.user_id, user_b=target_id
    )
