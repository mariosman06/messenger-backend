"""Group service managing group CRUD operations, membership actions, and permission checks."""

import logging
from uuid import UUID

from redis.asyncio import Redis

import src.database.queries as db_queries
import src.redis.queries as redis_queries
from src.database.connection import DatabaseManager
from src.database.models import Group, Membership
from src.services.errors import (
    InsufficientGroupPermissionError,
    handle_db_constraint_error,
    handle_db_not_found_error,
)
from src.services.websocket import WebSocketManager
from src.utils.tasks import spawn_task

logger = logging.getLogger(__name__)


class GroupService:
    """Coordinates group creation, membership governance, and cache invalidation."""

    def __init__(
        self, db: DatabaseManager, redis: Redis, ws_manager: WebSocketManager
    ) -> None:
        self._db = db
        self._redis = redis
        self._ws = ws_manager

    @handle_db_constraint_error()
    async def create_group(self, creator_id: UUID, name: str) -> tuple[Group, Membership]:
        """Creates a new group and registers the creator as its initial member."""
        group_entity = Group(name=name, created_by=creator_id)
        membership_entity = Membership(group_id=group_entity.group_id, user_id=creator_id)

        async with self._db.transaction() as conn:
            group = await db_queries.create_group(conn, group_entity)
            await db_queries.add_group_member(conn, membership_entity)
            logger.info(
                "Group '%s' created (id: %s) by creator %s.",
                group.name,
                group.group_id,
                creator_id,
            )

        spawn_task(self._ws.push_group_membership_change(creator_id, group.group_id, "JOIN"))
        return group, membership_entity

    async def list_group_members(self, group_id: UUID) -> list[Membership]:
        """Retrieves all memberships for a specific group."""
        async with self._db.connection() as conn:
            return await db_queries.list_group_memberships(conn, group_id=group_id)

    @handle_db_constraint_error()
    @handle_db_not_found_error()
    async def get_group_details(self, actor_id: UUID, group_id: UUID) -> Group:
        """Retrieves group details after verifying caller membership."""
        async with self._db.connection() as conn:
            group = await db_queries.get_group_by_id(conn, group_id=group_id)
            await db_queries.get_membership(conn, group_id=group_id, user_id=actor_id)
            return group

    async def list_user_groups(self, user_id: UUID) -> list[Group]:
        """Retrieves all groups that a user currently belongs to."""
        async with self._db.connection() as conn:
            return await db_queries.list_user_groups(conn, user_id=user_id)

    @handle_db_constraint_error()
    @handle_db_not_found_error()
    async def add_member(
        self, actor_id: UUID, group_id: UUID, target_user_id: UUID
    ) -> Membership:
        """Adds a target user to a group after verifying creator authorization."""
        async with self._db.transaction() as conn:
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

        spawn_task(self._ws.push_group_membership_change(target_user_id, group_id, "JOIN"))
        return membership

    @handle_db_constraint_error()
    @handle_db_not_found_error()
    async def remove_member(
        self, actor_id: UUID, group_id: UUID, target_user_id: UUID
    ) -> None:
        """Removes a member from a group. Allows self-removal or removal by group creator."""
        async with self._db.transaction() as conn:
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

            await db_queries.remove_group_member(
                conn, group_id=group_id, user_id=target_user_id
            )
            logger.info(
                "User %s removed from group %s (actor: %s).",
                target_user_id,
                group_id,
                actor_id,
            )

        spawn_task(self._ws.push_group_membership_change(target_user_id, group_id, "LEAVE"))

    async def _handle_group_deletion_side_effects(
        self, group_id: UUID, member_user_ids: list[UUID]
    ) -> None:
        """Cleans up Redis cache keys and notifies connected members via WebSockets."""
        str_member_ids = [str(uid) for uid in member_user_ids]
        await redis_queries.invalidate_deleted_group_cache(
            self._redis, str(group_id), str_member_ids
        )
        await self._ws.push_group_deleted(group_id)

    @handle_db_constraint_error()
    @handle_db_not_found_error()
    async def delete_group(self, actor_id: UUID, group_id: UUID) -> None:
        """Deletes a group and coordinates asynchronous teardown of cluster state."""
        async with self._db.transaction() as conn:
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

            memberships = await db_queries.list_group_memberships(conn, group_id=group_id)
            await db_queries.delete_group(conn, group_id=group_id, created_by=actor_id)
            logger.info("Group %s deleted by creator %s.", group_id, actor_id)

        member_user_ids = [m.user_id for m in memberships]
        spawn_task(self._handle_group_deletion_side_effects(group_id, member_user_ids))
