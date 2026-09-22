"""Message API router handling direct message and group message dispatch and timeline history."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.api.dependencies import CurrentUser, MessagingServiceDep
from src.api.schemas import (
    DirectMessageResponse,
    GroupMessageResponse,
    SendDirectMessageRequest,
    SendGroupMessageRequest,
)

router = APIRouter(prefix="/messages", tags=["Messages"])


@router.post(
    "/direct",
    response_model=DirectMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a direct message",
)
async def send_direct_message(
    payload: SendDirectMessageRequest,
    current_user: CurrentUser,
    message_service: MessagingServiceDep,
) -> DirectMessageResponse:
    """Sends a direct message to another user."""
    dm = await message_service.send_direct_message(
        sender_id=current_user.user_id,
        recipient_id=payload.recipient_id,
        content=payload.content,
    )
    return DirectMessageResponse.model_validate(dm)


@router.get(
    "/direct/{recipient_id}",
    response_model=list[DirectMessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Get direct message history",
)
async def get_dm_history(
    recipient_id: UUID,
    current_user: CurrentUser,
    message_service: MessagingServiceDep,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[DirectMessageResponse]:
    """Fetches direct message history with a specific user."""
    messages = await message_service.get_dm_history(
        actor_id=current_user.user_id,
        recipient_id=recipient_id,
        before=before,
        limit=limit,
    )
    return [DirectMessageResponse.model_validate(m) for m in messages]


@router.post(
    "/groups/{group_id}",
    response_model=GroupMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a group message",
)
async def send_group_message(
    group_id: UUID,
    payload: SendGroupMessageRequest,
    current_user: CurrentUser,
    message_service: MessagingServiceDep,
) -> GroupMessageResponse:
    """Sends a message to a group chat."""
    msg = await message_service.send_group_message(
        sender_id=current_user.user_id,
        group_id=group_id,
        content=payload.content,
    )
    return GroupMessageResponse.model_validate(msg)


@router.get(
    "/groups/{group_id}",
    response_model=list[GroupMessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Get group message history",
)
async def get_group_history(
    group_id: UUID,
    current_user: CurrentUser,
    message_service: MessagingServiceDep,
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[GroupMessageResponse]:
    """Fetches the message timeline for a group chat."""
    messages = await message_service.get_group_history(
        actor_id=current_user.user_id,
        group_id=group_id,
        before=before,
        limit=limit,
    )
    return [GroupMessageResponse.model_validate(m) for m in messages]
