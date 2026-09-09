from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def test_group_full_lifecycle_flow(client: AsyncClient) -> None:
    """Tests complete happy-path lifecycle: creation, listing, adding/removing members, leaving, and deletion."""
    # 1. Setup 3 distinct test users
    user_a = await UserFactory.create()
    user_b = await UserFactory.create()
    user_c = await UserFactory.create()

    # 2. User A creates a group
    create_res = await client.post(
        "/groups",
        json={"name": "Backend Engineering"},
        headers=user_a.headers,
    )
    assert create_res.status_code == 201
    group_data = create_res.json()
    group_id = group_data["group_id"]
    assert group_data["name"] == "Backend Engineering"
    assert group_data["created_by"] == str(user_a.user.user_id)

    # 3. User A lists their groups
    list_res_a = await client.get("/groups", headers=user_a.headers)
    assert list_res_a.status_code == 200
    assert len(list_res_a.json()) == 1
    assert list_res_a.json()[0]["group_id"] == group_id

    # 4. User A fetches group details
    detail_res_a = await client.get(f"/groups/{group_id}", headers=user_a.headers)
    assert detail_res_a.status_code == 200
    assert detail_res_a.json()["group_id"] == group_id

    # 5. User A adds User B to the group
    add_b_res = await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(user_b.user.user_id)},
        headers=user_a.headers,
    )
    assert add_b_res.status_code == 201
    assert add_b_res.json()["user_id"] == str(user_b.user.user_id)

    # 6. User B lists their groups and accesses group details
    list_res_b = await client.get("/groups", headers=user_b.headers)
    assert list_res_b.status_code == 200
    assert len(list_res_b.json()) == 1

    detail_res_b = await client.get(f"/groups/{group_id}", headers=user_b.headers)
    assert detail_res_b.status_code == 200

    # 7. User A adds User C to the group
    add_c_res = await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(user_c.user.user_id)},
        headers=user_a.headers,
    )
    assert add_c_res.status_code == 201

    # 8. User B voluntarily leaves the group
    leave_res = await client.delete(
        f"/groups/{group_id}/members/{user_b.user.user_id}",
        headers=user_b.headers,
    )
    assert leave_res.status_code == 204

    # Verify User B no longer sees the group in their list
    list_res_b_after = await client.get("/groups", headers=user_b.headers)
    assert len(list_res_b_after.json()) == 0

    # 9. User A (creator) removes User C from the group
    evict_res = await client.delete(
        f"/groups/{group_id}/members/{user_c.user.user_id}",
        headers=user_a.headers,
    )
    assert evict_res.status_code == 204

    # 10. User A deletes the entire group
    delete_group_res = await client.delete(f"/groups/{group_id}", headers=user_a.headers)
    assert delete_group_res.status_code == 204

    # 11. Confirm group no longer exists
    get_deleted_res = await client.get(f"/groups/{group_id}", headers=user_a.headers)
    assert get_deleted_res.status_code == 404


async def test_group_permissions_and_conflicts_flow(client: AsyncClient) -> None:
    """Tests authorization checks, forbidden actions, and conflict scenarios."""
    user_a = await UserFactory.create()
    user_b = await UserFactory.create()
    user_c = await UserFactory.create()

    # User A creates a group
    create_res = await client.post(
        "/groups",
        json={"name": "Security Guild"},
        headers=user_a.headers,
    )
    assert create_res.status_code == 201
    group_id = create_res.json()["group_id"]

    # 1. Non-member (User B) attempts to view group details -> 403 Forbidden
    unauth_get = await client.get(f"/groups/{group_id}", headers=user_b.headers)
    assert unauth_get.status_code == 403

    # 2. Non-member (User B) attempts to add a member -> 403 Forbidden
    unauth_add = await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(user_c.user.user_id)},
        headers=user_b.headers,
    )
    assert unauth_add.status_code == 403

    # User A adds User B to group
    await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(user_b.user.user_id)},
        headers=user_a.headers,
    )

    # 3. User A attempts to add User B again -> 409 Conflict (Already a member)
    duplicate_add = await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(user_b.user.user_id)},
        headers=user_a.headers,
    )
    assert duplicate_add.status_code == 409

    # User A adds User C to group
    await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(user_c.user.user_id)},
        headers=user_a.headers,
    )

    # 4. Non-creator member (User B) attempts to kick User C -> 403 Forbidden
    unauth_evict = await client.delete(
        f"/groups/{group_id}/members/{user_c.user.user_id}",
        headers=user_b.headers,
    )
    assert unauth_evict.status_code == 403

    # 5. Non-creator member (User B) attempts to delete the group -> 403 Forbidden
    unauth_delete = await client.delete(f"/groups/{group_id}", headers=user_b.headers)
    assert unauth_delete.status_code == 403


async def test_group_not_found_errors(client: AsyncClient) -> None:
    """Tests 404 responses for non-existent group IDs and user IDs."""
    user_a = await UserFactory.create()
    fake_group_id = uuid4()
    fake_user_id = uuid4()

    # Get non-existent group -> 404
    res_get = await client.get(f"/groups/{fake_group_id}", headers=user_a.headers)
    assert res_get.status_code == 404

    # Delete non-existent group -> 404
    res_del = await client.delete(f"/groups/{fake_group_id}", headers=user_a.headers)
    assert res_del.status_code == 404

    # Create real group then attempt to add non-existent user -> 404
    create_res = await client.post(
        "/groups",
        json={"name": "DevOps"},
        headers=user_a.headers,
    )
    assert create_res.status_code == 201
    real_group_id = create_res.json()["group_id"]

    add_fake_user = await client.post(
        f"/groups/{real_group_id}/members",
        json={"user_id": str(fake_user_id)},
        headers=user_a.headers,
    )
    assert add_fake_user.status_code == 404
