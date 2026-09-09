import pytest
from httpx import AsyncClient

from tests.factories import TestUser


@pytest.mark.asyncio
async def test_direct_message_lifecycle(client: AsyncClient, user_factory):
    """Tests full DM flow: friendship establishment -> exchange DMs -> fetch timeline history."""
    alice: TestUser = await user_factory(username="alice_dm_lifecycle")
    bob: TestUser = await user_factory(username="bob_dm_lifecycle")

    # 1. Establish friendship between Alice and Bob
    await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    await client.post(
        f"/friends/requests/{alice.user.user_id}/accept",
        headers=bob.headers,
    )

    # 2. Alice sends a DM to Bob
    send_resp = await client.post(
        "/messages/direct",
        json={"recipient_id": str(bob.user.user_id), "content": "Hello Bob!"},
        headers=alice.headers,
    )
    assert send_resp.status_code == 201
    msg_data = send_resp.json()
    assert msg_data["sender_id"] == str(alice.user.user_id)
    assert msg_data["recipient_id"] == str(bob.user.user_id)
    assert msg_data["content"] == "Hello Bob!"

    # 3. Bob sends a reply DM to Alice
    reply_resp = await client.post(
        "/messages/direct",
        json={"recipient_id": str(alice.user.user_id), "content": "Hey Alice!"},
        headers=bob.headers,
    )
    assert reply_resp.status_code == 201

    # 4. Alice fetches conversation history with Bob
    alice_history = await client.get(
        f"/messages/direct/{bob.user.user_id}",
        headers=alice.headers,
    )
    assert alice_history.status_code == 200
    messages = alice_history.json()
    assert len(messages) == 2

    # 5. Bob fetches conversation history with Alice
    bob_history = await client.get(
        f"/messages/direct/{alice.user.user_id}",
        headers=bob.headers,
    )
    assert bob_history.status_code == 200
    assert len(bob_history.json()) == 2


@pytest.mark.asyncio
async def test_direct_message_not_allowed_if_not_friends(client: AsyncClient, user_factory):
    """Verifies that non-friends are blocked (403 Forbidden) from sending DMs or viewing DM history."""
    alice = await user_factory(username="alice_dm_auth")
    charlie = await user_factory(username="charlie_dm_auth")

    # 1. Charlie attempts to send a DM to Alice without being friends
    send_resp = await client.post(
        "/messages/direct",
        json={"recipient_id": str(alice.user.user_id), "content": "Unsolicited DM"},
        headers=charlie.headers,
    )
    assert send_resp.status_code == 403

    # 2. Charlie attempts to view DM history with Alice
    history_resp = await client.get(
        f"/messages/direct/{alice.user.user_id}",
        headers=charlie.headers,
    )
    assert history_resp.status_code == 403


@pytest.mark.asyncio
async def test_direct_message_pagination(client: AsyncClient, user_factory):
    """Tests cursor-based pagination using `before` timestamp and `limit` on DMs."""
    alice: TestUser = await user_factory(username="alice_dm_page")
    bob: TestUser = await user_factory(username="bob_dm_page")

    await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    await client.post(
        f"/friends/requests/{alice.user.user_id}/accept",
        headers=bob.headers,
    )

    # Seed 5 consecutive messages
    for i in range(5):
        await client.post(
            "/messages/direct",
            json={"recipient_id": str(bob.user.user_id), "content": f"Message {i}"},
            headers=alice.headers,
        )

    # 1. Fetch first page with limit=2
    page_1_resp = await client.get(
        f"/messages/direct/{bob.user.user_id}",
        params={"limit": 2},
        headers=alice.headers,
    )
    assert page_1_resp.status_code == 200
    page_1 = page_1_resp.json()
    assert len(page_1) == 2

    # 2. Extract oldest timestamp from page 1 to use as 'before' cursor
    oldest_ts = page_1[-1]["created_at"]

    # 3. Fetch second page
    page_2_resp = await client.get(
        f"/messages/direct/{bob.user.user_id}",
        params={"before": oldest_ts, "limit": 2},
        headers=alice.headers,
    )
    assert page_2_resp.status_code == 200
    page_2 = page_2_resp.json()
    assert len(page_2) == 2

    # Verify no overlapping messages between pages
    page_1_ids = {m["message_id"] for m in page_1}
    page_2_ids = {m["message_id"] for m in page_2}
    assert page_1_ids.isdisjoint(page_2_ids)


@pytest.mark.asyncio
async def test_group_message_lifecycle(client: AsyncClient, user_factory):
    """Tests group messaging flow: create group -> add member -> exchange messages -> fetch timeline."""
    alice = await user_factory(username="creator_grp_lc")
    bob = await user_factory(username="member_grp_lc")

    # 1. Alice creates a group
    create_group_resp = await client.post(
        "/groups",
        json={"name": "Dev Team"},
        headers=alice.headers,
    )
    assert create_group_resp.status_code == 201
    group_id = create_group_resp.json()["group_id"]

    # 2. Alice adds Bob to the group
    add_member_resp = await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    assert add_member_resp.status_code == 201

    # 3. Alice posts a message to the group
    alice_msg = await client.post(
        f"/messages/groups/{group_id}",
        json={"content": "Welcome to the team!"},
        headers=alice.headers,
    )
    assert alice_msg.status_code == 201
    msg_data = alice_msg.json()
    assert msg_data["group_id"] == group_id
    assert msg_data["sender_id"] == str(alice.user.user_id)

    # 4. Bob posts a response to the group
    bob_msg = await client.post(
        f"/messages/groups/{group_id}",
        json={"content": "Glad to be here!"},
        headers=bob.headers,
    )
    assert bob_msg.status_code == 201

    # 5. Bob fetches group message timeline
    history_resp = await client.get(
        f"/messages/groups/{group_id}",
        headers=bob.headers,
    )
    assert history_resp.status_code == 200
    timeline = history_resp.json()
    assert len(timeline) == 2


@pytest.mark.asyncio
async def test_group_message_non_member_forbidden(client: AsyncClient, user_factory):
    """Verifies non-members cannot post messages or view message history in private groups."""
    alice = await user_factory(username="alice_grp_auth")
    charlie = await user_factory(username="charlie_grp_auth")

    # 1. Alice creates a group
    create_group_resp = await client.post(
        "/groups",
        json={"name": "Secret Group"},
        headers=alice.headers,
    )
    group_id = create_group_resp.json()["group_id"]

    # 2. Charlie (non-member) tries to post a message
    send_resp = await client.post(
        f"/messages/groups/{group_id}",
        json={"content": "Can I join?"},
        headers=charlie.headers,
    )
    assert send_resp.status_code == 403

    # 3. Charlie (non-member) tries to view group history
    history_resp = await client.get(
        f"/messages/groups/{group_id}",
        headers=charlie.headers,
    )
    assert history_resp.status_code == 403


@pytest.mark.asyncio
async def test_group_message_pagination(client: AsyncClient, user_factory):
    """Tests cursor-based pagination using `before` timestamp and `limit` on group messages."""
    alice: TestUser = await user_factory(username="alice_grp_page")

    group_resp = await client.post(
        "/groups",
        json={"name": "Pagination Test Group"},
        headers=alice.headers,
    )
    group_id = group_resp.json()["group_id"]

    for i in range(4):
        await client.post(
            f"/messages/groups/{group_id}",
            json={"content": f"Group Msg {i}"},
            headers=alice.headers,
        )

    # Fetch page with limit=2
    page_1_resp = await client.get(
        f"/messages/groups/{group_id}",
        params={"limit": 2},
        headers=alice.headers,
    )
    assert page_1_resp.status_code == 200
    page_1 = page_1_resp.json()
    assert len(page_1) == 2

    # Fetch remaining records using the cursor
    oldest_ts = page_1[-1]["created_at"]
    page_2_resp = await client.get(
        f"/messages/groups/{group_id}",
        params={"before": oldest_ts, "limit": 5},
        headers=alice.headers,
    )
    assert page_2_resp.status_code == 200
    page_2 = page_2_resp.json()
    assert len(page_2) == 2
