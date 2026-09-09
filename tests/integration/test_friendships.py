import pytest
from httpx import AsyncClient

from tests.factories import TestUser


@pytest.mark.asyncio
async def test_full_friend_request_lifecycle(client: AsyncClient, user_factory):
    """Tests complete flow: send request -> verify pending -> accept -> verify friends list & status."""
    alice: TestUser = await user_factory(username="alice")
    bob: TestUser = await user_factory(username="bob")

    # 1. Alice sends a friend request to Bob
    send_resp = await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    assert send_resp.status_code == 201

    # 2. Bob checks his pending requests
    pending_resp = await client.get(
        "/friends/requests/pending",
        headers=bob.headers,
    )
    assert pending_resp.status_code == 200
    pending_list = pending_resp.json()
    assert len(pending_list) == 1
    assert pending_list[0]["requester_id"] == str(alice.user.user_id)
    assert not pending_list[0]["accepted"]

    # 3. Alice checks status with Bob
    status_resp = await client.get(
        f"/friends/{bob.user.user_id}/status",
        headers=alice.headers,
    )
    assert status_resp.status_code == 200
    assert not status_resp.json()["accepted"]

    # 4. Bob accepts Alice's request
    accept_resp = await client.post(
        f"/friends/requests/{alice.user.user_id}/accept",
        headers=bob.headers,
    )
    assert accept_resp.status_code == 200

    # 5. Alice checks her friends list
    alice_friends = await client.get("/friends", headers=alice.headers)
    assert alice_friends.status_code == 200
    assert len(alice_friends.json()) == 1

    # 6. Bob checks his friends list
    bob_friends = await client.get("/friends", headers=bob.headers)
    assert bob_friends.status_code == 200
    assert len(bob_friends.json()) == 1

    # 7. Check status returns ACCEPTED
    final_status = await client.get(
        f"/friends/{bob.user.user_id}/status",
        headers=alice.headers,
    )
    assert final_status.status_code == 200
    assert final_status.json()["accepted"]


@pytest.mark.asyncio
async def test_decline_friend_request_flow(client: AsyncClient, user_factory):
    """Tests declining an incoming friend request."""
    alice = await user_factory()
    bob = await user_factory()

    await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )

    # Bob declines the request
    decline_resp = await client.delete(
        f"/friends/{alice.user.user_id}",
        headers=bob.headers,
    )
    assert decline_resp.status_code == 204

    # Verify pending requests list is now empty
    pending_resp = await client.get(
        "/friends/requests/pending",
        headers=bob.headers,
    )
    assert pending_resp.status_code == 200
    assert len(pending_resp.json()) == 0


@pytest.mark.asyncio
async def test_remove_friend_flow(client: AsyncClient, user_factory):
    """Tests unfriending an established friend."""
    alice = await user_factory()
    bob = await user_factory()

    # Establish friendship
    await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    await client.post(
        f"/friends/requests/{alice.user.user_id}/accept",
        headers=bob.headers,
    )

    # Alice unfriends Bob
    remove_resp = await client.delete(
        f"/friends/{bob.user.user_id}",
        headers=alice.headers,
    )
    assert remove_resp.status_code == 204

    # Verify both friends lists are empty
    alice_friends = await client.get("/friends", headers=alice.headers)
    bob_friends = await client.get("/friends", headers=bob.headers)
    assert len(alice_friends.json()) == 0
    assert len(bob_friends.json()) == 0
