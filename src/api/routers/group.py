"""Group management API router handling group creation, details, deletion, and membership."""

from uuid import UUID

from fastapi import APIRouter, status

from src.api.dependencies import CurrentUser, GroupServiceDep
from src.api.schemas import (
    AddGroupMemberRequest,
    CreateGroupRequest,
    GroupResponse,
    MembershipResponse,
)

router = APIRouter(prefix="/groups", tags=["Groups"])


@router.post(
    "",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new group",
)
async def create_group(
    payload: CreateGroupRequest,
    current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> GroupResponse:
    """Creates a new group chat entity with the calling user as creator and initial member."""
    group, _ = await group_service.create_group(
        creator_id=current_user.user_id, name=payload.name
    )
    return GroupResponse.model_validate(group)


@router.get(
    "",
    response_model=list[GroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List joined groups",
)
async def list_groups(
    current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> list[GroupResponse]:
    """Retrieves all active groups that the calling user belongs to."""
    groups = await group_service.list_user_groups(user_id=current_user.user_id)
    return [GroupResponse.model_validate(g) for g in groups]


@router.get(
    "/{group_id}",
    response_model=GroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Get group details",
)
async def get_group(
    group_id: UUID,
    current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> GroupResponse:
    """Fetches details for a specific group if the calling user is an active member."""
    group = await group_service.get_group_details(
        actor_id=current_user.user_id, group_id=group_id
    )
    return GroupResponse.model_validate(group)


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a group",
)
async def delete_group(
    group_id: UUID,
    current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> None:
    """Deletes an entire group. Restricted exclusively to the group's creator."""
    await group_service.delete_group(actor_id=current_user.user_id, group_id=group_id)


@router.post(
    "/{group_id}/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to group",
)
async def add_member(
    group_id: UUID,
    payload: AddGroupMemberRequest,
    current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> MembershipResponse:
    """Adds a target user to an existing group."""
    membership = await group_service.add_member(
        actor_id=current_user.user_id,
        group_id=group_id,
        target_user_id=payload.user_id,
    )
    return MembershipResponse.model_validate(membership)


@router.delete(
    "/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member or leave group",
)
async def remove_member(
    group_id: UUID,
    user_id: UUID,
    current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> None:
    """Removes a user from a group (handles self-removal or creator removal)."""
    await group_service.remove_member(
        actor_id=current_user.user_id, group_id=group_id, target_user_id=user_id
    )


@router.get(
    "/{group_id}/members",
    response_model=list[MembershipResponse],
    status_code=status.HTTP_200_OK,
    summary="List group members",
)
async def list_group_members(
    group_id: UUID,
    _current_user: CurrentUser,
    group_service: GroupServiceDep,
) -> list[MembershipResponse]:
    """Retrieves all active members for a specific group."""
    memberships = await group_service.list_group_members(group_id=group_id)
    return [MembershipResponse.model_validate(m) for m in memberships]
