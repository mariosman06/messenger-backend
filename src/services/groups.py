"""Group service group CRUD operations, membership actions, and creator permission checks."""

import logging
from uuid import UUID

from src.database import queries as db_queries
from src.database.connection import get_conn, get_transaction
from src.database.models import Group, Membership
from src.services.errors import (
    InsufficientGroupPermissionError,
    handle_db_constraint_error,
    handle_db_not_found_error,
)

logger = logging.getLogger(__name__)


@handle_db_constraint_error()
async def create_group(creator_id: UUID, name: str) -> tuple[Group, Membership]:
    """Creates a new group and automatically registers the creator as its initial member."""
    group_entity = Group(name=name, created_by=creator_id)
    membership_entity = Membership(group_id=group_entity.group_id, user_id=creator_id)

    async with get_transaction() as conn:
        group = await db_queries.create_group(conn, group_entity)
        await db_queries.add_group_member(conn, membership_entity)
        logger.info(
            "Group '%s' created (id: %s) by creator %s.",
            group.name,
            group.group_id,
            creator_id,
        )

    return group, membership_entity


@handle_db_constraint_error()
@handle_db_not_found_error()
async def get_group_details(actor_id: UUID, group_id: UUID) -> Group:
    """Retrieves group details after verifying group existence and active membership."""
    async with get_conn() as conn:
        group = await db_queries.get_group_by_id(conn, group_id=group_id)
        await db_queries.get_membership(conn, group_id=group_id, user_id=actor_id)
        return group


async def list_user_groups(user_id: UUID) -> list[Group]:
    """Retrieves all groups that a user currently belongs to."""
    async with get_conn() as conn:
        return await db_queries.list_user_groups(conn, user_id=user_id)


@handle_db_constraint_error()
@handle_db_not_found_error()
async def add_member(actor_id: UUID, group_id: UUID, target_user_id: UUID) -> Membership:
    """Adds a target user to a group after validating caller permissions."""
    async with get_transaction() as conn:
        group = await db_queries.get_group_by_id(conn, group_id=group_id)
        if group.created_by != actor_id:
            logger.warning(
                "User %s attempted to add member to group %s without creator permissions.",
                actor_id,
                group_id,
            )
            raise InsufficientGroupPermissionError(
                "Only the group creator can add new members."
            )

        membership_entity = Membership(group_id=group_id, user_id=target_user_id)
        membership = await db_queries.add_group_member(conn, membership_entity)
        logger.info(
            "User %s added to group %s by actor %s.",
            target_user_id,
            group_id,
            actor_id,
        )
        return membership


@handle_db_constraint_error()
@handle_db_not_found_error()
async def remove_member(actor_id: UUID, group_id: UUID, target_user_id: UUID) -> None:
    """Removes a member from a group. Allows self-removal or removal by group creator."""
    async with get_transaction() as conn:
        group = await db_queries.get_group_by_id(conn, group_id=group_id)

        if target_user_id == group.created_by:
            logger.warning(
                "Creator %s attempted to leave group %s directly.",
                target_user_id,
                group_id,
            )
            raise InsufficientGroupPermissionError(
                "Group creator cannot leave the group. Delete the group instead."
            )

        is_self_removal = actor_id == target_user_id
        is_creator = group.created_by == actor_id

        if not (is_self_removal or is_creator):
            logger.warning(
                "User %s attempted to remove member %s from group %s without permissions.",
                actor_id,
                target_user_id,
                group_id,
            )
            raise InsufficientGroupPermissionError(
                "Only the group creator can remove other members."
            )

        await db_queries.remove_group_member(conn, group_id=group_id, user_id=target_user_id)
        logger.info(
            "User %s removed from group %s (actor: %s).",
            target_user_id,
            group_id,
            actor_id,
        )


@handle_db_constraint_error()
@handle_db_not_found_error()
async def delete_group(actor_id: UUID, group_id: UUID) -> None:
    """Deletes a group. Restricted exclusively to the group creator."""
    async with get_transaction() as conn:
        group = await db_queries.get_group_by_id(conn, group_id=group_id)

        if group.created_by != actor_id:
            logger.warning(
                "User %s attempted to delete group %s without creator permissions.",
                actor_id,
                group_id,
            )
            raise InsufficientGroupPermissionError(
                "Only the group creator can delete this group."
            )

        await db_queries.delete_group(conn, group_id=group_id, created_by=actor_id)
        logger.info("Group %s deleted by creator %s.", group_id, actor_id)
