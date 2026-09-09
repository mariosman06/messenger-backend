import pytest
from httpx import AsyncClient

from tests.factories import TestUser


@pytest.mark.asyncio
async def test_user_registration_and_login_lifecycle(client: AsyncClient):
    """Tests the complete end-to-end user authentication lifecycle: registration,

    profile retrieval, duplicate prevention, invalid credential handling, and re-login.
    """
    username = "integration_test_user"
    password = "SecurePassword123!"

    # 1. Register a new user account
    register_resp = await client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )
    assert register_resp.status_code == 201
    reg_data = register_resp.json()
    assert reg_data["user"]["username"] == username
    assert reg_data["user"]["deactivated"] is False
    assert "access_token" in reg_data["tokens"]
    assert "refresh_token" in reg_data["tokens"]

    initial_access_token = reg_data["tokens"]["access_token"]
    user_id = reg_data["user"]["user_id"]

    # 2. Retrieve profile using the newly issued access token
    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {initial_access_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["user_id"] == user_id
    assert me_resp.json()["username"] == username

    # 3. Prevent registration with duplicate username
    dup_resp = await client.post(
        "/auth/register",
        json={"username": username, "password": "AnotherPassword123!"},
    )
    assert dup_resp.status_code in (400, 409)

    # 4. Reject login attempt with wrong password
    bad_login_resp = await client.post(
        "/auth/login",
        json={"username": username, "password": "WrongPassword!"},
    )
    assert bad_login_resp.status_code == 401

    # 5. Login successfully with correct credentials
    login_resp = await client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["user"]["user_id"] == user_id
    assert login_data["tokens"]["access_token"] != initial_access_token


@pytest.mark.asyncio
async def test_token_rotation_and_reuse_detection_security_flow(
    client: AsyncClient, user_factory
):
    """Tests automatic refresh token rotation and security intervention (family revocation)

    when a consumed refresh token is maliciously reused.
    """
    user: TestUser = await user_factory()
    original_refresh_token = user.tokens.refresh_token

    # 1. Perform legitimate refresh token rotation
    refresh_resp_1 = await client.post(
        "/auth/refresh",
        json={"refresh_token": original_refresh_token},
    )
    assert refresh_resp_1.status_code == 200
    tokens_v1 = refresh_resp_1.json()
    assert tokens_v1["refresh_token"] != original_refresh_token

    # 2. Verify rotated access token works against protected routes
    me_resp = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {tokens_v1['access_token']}"},
    )
    assert me_resp.status_code == 200

    # 3. Simulate reuse attack: Attempt to refresh using the consumed refresh token
    reuse_resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": original_refresh_token},
    )
    assert reuse_resp.status_code in (400, 401)

    # 4. Verify reuse detection revoked the entire refresh token family
    # (The legitimate tokens_v1 refresh token must now fail)
    revoked_refresh_resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": tokens_v1["refresh_token"]},
    )
    assert revoked_refresh_resp.status_code in (400, 401)


@pytest.mark.asyncio
async def test_logout_and_session_revocation_flow(client: AsyncClient, user_factory):
    """Tests explicit user logout and immediate revocation of both access and refresh tokens."""
    user: TestUser = await user_factory()

    # 1. Confirm session is active
    pre_logout_me = await client.get("/auth/me", headers=user.headers)
    assert pre_logout_me.status_code == 200

    # 2. Execute session logout
    logout_resp = await client.post(
        "/auth/logout",
        json={"refresh_token": user.tokens.refresh_token},
        headers=user.headers,
    )
    assert logout_resp.status_code == 204

    # 3. Confirm access token is revoked
    post_logout_me = await client.get("/auth/me", headers=user.headers)
    assert post_logout_me.status_code == 401

    # 4. Confirm refresh token is revoked
    post_logout_refresh = await client.post(
        "/auth/refresh",
        json={"refresh_token": user.tokens.refresh_token},
    )
    assert post_logout_refresh.status_code in (400, 401)
