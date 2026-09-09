"""Friendship API router handling friend requests, status checks, and friend management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

import src.services.friendships as friendship_service
from src.api.dependencies import get_current_user
from src.api.schemas import FriendshipResponse, SendFriendRequest
from src.database.models import User

router = APIRouter(prefix="/friends", tags=["Friendships"])


# Friend Requests


@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    summary="Send a friend request",
)
async def send_request(
    payload: SendFriendRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Dispatches a new pending friend request to a target user."""
    await friendship_service.send_request(
        requester_id=current_user.user_id, addressee_id=payload.addressee_id
    )
    return {"message": "Friend request sent successfully."}


@router.get(
    "/requests/pending",
    response_model=list[FriendshipResponse],
    status_code=status.HTTP_200_OK,
    summary="List pending incoming friend requests",
)
async def list_pending_requests(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[FriendshipResponse]:
    """Retrieves all incoming pending friend requests awaiting action."""
    return [
        FriendshipResponse.model_validate(p)
        for p in await friendship_service.get_pending(user_id=current_user.user_id)
    ]


@router.post(
    "/requests/{requester_id}/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept a pending friend request",
)
async def accept_request(
    requester_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """Accepts an incoming pending friend request."""
    await friendship_service.accept_request(
        addressee_id=current_user.user_id, requester_id=requester_id
    )
    return {"message": "Friend request accepted."}


# Friendships


@router.get(
    "",
    response_model=list[FriendshipResponse],
    status_code=status.HTTP_200_OK,
    summary="List all accepted friends",
)
async def list_friends(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[FriendshipResponse]:
    """Retrieves all active, accepted friendships for the calling user."""
    return [
        FriendshipResponse.model_validate(f)
        for f in await friendship_service.get_friends(user_id=current_user.user_id)
    ]


@router.get(
    "/{target_id}/status",
    response_model=FriendshipResponse,
    status_code=status.HTTP_200_OK,
    summary="Get friendship status with a specific user",
)
async def get_status(
    target_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
) -> FriendshipResponse:
    """Fetches the friendship record establishing relationship status with a user."""
    return FriendshipResponse.model_validate(
        await friendship_service.get_status(user_a=current_user.user_id, user_b=target_id)
    )


@router.delete(
    "/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a friend, cancel a request, or decline a request",
)
async def remove_or_decline(
    target_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Terminates an existing friendship or cancels/declines an active request."""
    await friendship_service.remove_or_decline_friendship(
        user_a=current_user.user_id, user_b=target_id
    )
