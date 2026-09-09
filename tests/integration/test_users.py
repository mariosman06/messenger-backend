from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


async def test_get_current_user_profile(client: AsyncClient) -> None:
    """Tests retrieving the authenticated user's own profile."""
    user_a = await UserFactory.create()

    res = await client.get("/users/me", headers=user_a.headers)
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == str(user_a.user.user_id)
    assert data["username"] == user_a.user.username


async def test_user_lookup_by_username_and_id(client: AsyncClient) -> None:
    """Tests looking up another user profile by username and UUID."""
    user_a = await UserFactory.create()
    user_b = await UserFactory.create()

    # Fetch profile by username
    res_username = await client.get(
        f"/users/by-username/{user_b.user.username}",
        headers=user_a.headers,
    )
    assert res_username.status_code == 200
    assert res_username.json()["user_id"] == str(user_b.user.user_id)

    # Fetch profile by UUID
    res_id = await client.get(
        f"/users/{user_b.user.user_id}",
        headers=user_a.headers,
    )
    assert res_id.status_code == 200
    assert res_id.json()["username"] == user_b.user.username


async def test_user_lookup_not_found_errors(client: AsyncClient) -> None:
    """Tests 404 responses for non-existent usernames and user IDs."""
    user_a = await UserFactory.create()
    fake_user_id = uuid4()

    # Non-existent username
    res_username = await client.get(
        "/users/by-username/nonexistent_user_999",
        headers=user_a.headers,
    )
    assert res_username.status_code == 404

    # Non-existent UUID
    res_id = await client.get(f"/users/{fake_user_id}", headers=user_a.headers)
    assert res_id.status_code == 404


async def test_user_account_lifecycle_flow(client: AsyncClient) -> None:
    """Tests account deactivation, reactivation, and permanent deletion."""
    user_a = await UserFactory.create()
    user_b = await UserFactory.create()

    # 1. Deactivate account
    deactivate_res = await client.post("/users/me/deactivate", headers=user_a.headers)
    assert deactivate_res.status_code == 204

    # 2. Reactivate account
    reactivate_res = await client.post("/users/me/reactivate", headers=user_a.headers)
    assert reactivate_res.status_code == 204

    # 3. Permanently delete account
    delete_res = await client.delete("/users/me", headers=user_a.headers)
    assert delete_res.status_code == 204

    # 4. Verify account is gone when fetched by another user
    lookup_res = await client.get(f"/users/{user_a.user.user_id}", headers=user_b.headers)
    assert lookup_res.status_code == 404


async def test_unauthenticated_user_endpoint_access(client: AsyncClient) -> None:
    """Tests that user endpoints reject unauthenticated requests with 401 Unauthorized."""
    res_me = await client.get("/users/me")
    assert res_me.status_code == 401

    res_username = await client.get("/users/by-username/testuser")
    assert res_username.status_code == 401
