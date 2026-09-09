"""Message API router handling direct message and group message dispatch and history queries."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

import src.services.messages as message_service
from src.api.dependencies import get_current_user
from src.api.schemas import (
    DirectMessageResponse,
    GroupMessageResponse,
    SendDirectMessageRequest,
    SendGroupMessageRequest,
)
from src.database.models import User

router = APIRouter(prefix="/messages", tags=["Messages"])


# Direct Messages


@router.post(
    "/direct",
    response_model=DirectMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a direct message",
)
async def send_direct_message(
    payload: SendDirectMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> DirectMessageResponse:
    """Sends a direct message to another user."""
    return DirectMessageResponse.model_validate(
        await message_service.send_direct_message(
            sender_id=current_user.user_id,
            recipient_id=payload.recipient_id,
            content=payload.content,
        )
    )


@router.get(
    "/direct/{recipient_id}",
    response_model=list[DirectMessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Get direct message history",
)
async def get_dm_history(
    recipient_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[DirectMessageResponse]:
    """Fetches direct message history with a specific user."""
    return [
        DirectMessageResponse.model_validate(m)
        for m in await message_service.get_dm_history(
            actor_id=current_user.user_id,
            recipient_id=recipient_id,
            before=before,
            limit=limit,
        )
    ]


# Group Messages


@router.post(
    "/groups/{group_id}",
    response_model=GroupMessageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a group message",
)
async def send_group_message(
    group_id: UUID,
    payload: SendGroupMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> GroupMessageResponse:
    """Sends a message to a group chat."""
    return GroupMessageResponse.model_validate(
        await message_service.send_group_message(
            sender_id=current_user.user_id,
            group_id=group_id,
            content=payload.content,
        )
    )


@router.get(
    "/groups/{group_id}",
    response_model=list[GroupMessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Get group message history",
)
async def get_group_history(
    group_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[GroupMessageResponse]:
    """Fetches the message timeline for a group chat."""
    return [
        GroupMessageResponse.model_validate(m)
        for m in await message_service.get_group_history(
            actor_id=current_user.user_id,
            group_id=group_id,
            before=before,
            limit=limit,
        )
    ]
