import asyncio
import json

import httpx
import pytest
import websockets


async def _establish_friendship(http_client: httpx.AsyncClient, sender, recipient) -> None:
    """Creates and accepts a bilateral friendship request between two test users."""
    sender_headers = {"Authorization": f"Bearer {sender.tokens.access_token}"}
    recipient_headers = {"Authorization": f"Bearer {recipient.tokens.access_token}"}

    req_res = await http_client.post(
        "/friends/requests",
        json={"addressee_id": str(recipient.user.user_id)},
        headers=sender_headers,
    )
    assert req_res.status_code in (200, 201)

    accept_res = await http_client.post(
        f"/friends/requests/{sender.user.user_id}/accept",
        headers=recipient_headers,
    )
    assert accept_res.status_code in (200, 201, 204)


@pytest.mark.asyncio
async def test_cross_worker_websocket_broadcast(multi_worker_server, user_factory):
    """Verifies HTTP direct messages route across distinct worker processes via Redis Pub/Sub."""
    server_url = multi_worker_server
    ws_url = server_url.replace("http://", "ws://") + "/ws"

    sender = await user_factory()
    recipient = await user_factory()

    async with httpx.AsyncClient(base_url=server_url) as http_client:
        await _establish_friendship(http_client, sender, recipient)

    async with websockets.connect(
        f"{ws_url}?token={recipient.tokens.access_token}"
    ) as ws_recipient:
        async with httpx.AsyncClient(base_url=server_url) as http_client:
            response = await http_client.post(
                "/messages/direct",
                json={
                    "recipient_id": str(recipient.user.user_id),
                    "content": "Hello across Uvicorn workers!",
                },
                headers={"Authorization": f"Bearer {sender.tokens.access_token}"},
            )
            assert response.status_code == 201

        raw_msg = await asyncio.wait_for(ws_recipient.recv(), timeout=3.0)
        event = json.loads(raw_msg)

        assert event["event"] == "direct_message"
        assert event["content"] == "Hello across Uvicorn workers!"
        assert event["sender_id"] == str(sender.user.user_id)
        assert event["recipient_id"] == str(recipient.user.user_id)


@pytest.mark.asyncio
async def test_sequential_direct_messages_ordering(multi_worker_server, user_factory):
    """Ensures sequential direct messages are delivered in strict FIFO order over WebSockets."""
    server_url = multi_worker_server
    ws_url = server_url.replace("http://", "ws://") + "/ws"

    sender = await user_factory()
    recipient = await user_factory()

    async with httpx.AsyncClient(base_url=server_url) as http_client:
        await _establish_friendship(http_client, sender, recipient)

    num_messages = 10

    async with websockets.connect(
        f"{ws_url}?token={recipient.tokens.access_token}"
    ) as ws_recipient:
        async with httpx.AsyncClient(base_url=server_url) as http_client:
            for i in range(num_messages):
                resp = await http_client.post(
                    "/messages/direct",
                    json={
                        "recipient_id": str(recipient.user.user_id),
                        "content": f"Ordered message #{i}",
                    },
                    headers={"Authorization": f"Bearer {sender.tokens.access_token}"},
                )
                assert resp.status_code == 201

        for i in range(num_messages):
            raw_msg = await asyncio.wait_for(ws_recipient.recv(), timeout=5.0)
            event = json.loads(raw_msg)
            assert event["event"] == "direct_message"
            assert event["content"] == f"Ordered message #{i}"


@pytest.mark.asyncio
async def test_concurrent_group_chat_broadcast_heavy(multi_worker_server, user_factory):
    """Stress tests real-time Pub/Sub fanout delivery under a heavy burst of concurrent group messages."""
    server_url = multi_worker_server
    ws_url = server_url.replace("http://", "ws://") + "/ws"

    owner = await user_factory()
    member1 = await user_factory()
    member2 = await user_factory()

    async with httpx.AsyncClient(base_url=server_url) as http_client:
        create_res = await http_client.post(
            "/groups",
            json={"name": "Heavy Broadcast Group"},
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )
        group_id = create_res.json()["group_id"]

        for mem in [member1, member2]:
            await http_client.post(
                f"/groups/{group_id}/members",
                json={"user_id": str(mem.user.user_id)},
                headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
            )

    burst_count = 50

    async with (
        websockets.connect(f"{ws_url}?token={member1.tokens.access_token}") as ws1,
        websockets.connect(f"{ws_url}?token={member2.tokens.access_token}") as ws2,
    ):
        async with httpx.AsyncClient(base_url=server_url) as http_client:

            async def post_group_msg(i: int):
                return await http_client.post(
                    f"/messages/groups/{group_id}",
                    json={"content": f"Group burst #{i}"},
                    headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
                )

            responses = await asyncio.gather(*[post_group_msg(i) for i in range(burst_count)])
            for resp in responses:
                assert resp.status_code == 201

        for ws in (ws1, ws2):
            received = set()
            for _ in range(burst_count):
                raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
                event = json.loads(raw)
                assert event["event"] == "group_message"
                assert event["group_id"] == group_id
                received.add(event["content"])
            assert len(received) == burst_count


@pytest.mark.asyncio
async def test_race_condition_concurrent_group_joins(multi_worker_server, user_factory):
    """Validates database concurrency isolation during high-volume simultaneous group join operations."""
    server_url = multi_worker_server
    owner = await user_factory()
    new_members = [await user_factory() for _ in range(30)]

    async with httpx.AsyncClient(base_url=server_url) as http_client:
        create_res = await http_client.post(
            "/groups",
            json={"name": "Mass Join Group"},
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )
        group_id = create_res.json()["group_id"]

        async def join_group(member):
            return await http_client.post(
                f"/groups/{group_id}/members",
                json={"user_id": str(member.user.user_id)},
                headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
            )

        responses = await asyncio.gather(*[join_group(m) for m in new_members])
        for r in responses:
            assert r.status_code in (200, 201)

        members_res = await http_client.get(
            f"/groups/{group_id}/members",
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )
        assert members_res.status_code == 200
        assert len(members_res.json()) == 31


@pytest.mark.asyncio
async def test_race_condition_double_action_prevention(multi_worker_server, user_factory):
    """Verifies idempotent handling and prevention of race conditions for duplicate leave requests."""
    server_url = multi_worker_server
    owner = await user_factory()
    member = await user_factory()

    async with httpx.AsyncClient(base_url=server_url) as http_client:
        await _establish_friendship(http_client, owner, member)

        create_res = await http_client.post(
            "/groups",
            json={"name": "Double Action Group"},
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )
        group_id = create_res.json()["group_id"]

        await http_client.post(
            f"/groups/{group_id}/members",
            json={"user_id": str(member.user.user_id)},
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )

        async def leave_request():
            return await http_client.delete(
                f"/groups/{group_id}/members/{member.user.user_id}",
                headers={"Authorization": f"Bearer {member.tokens.access_token}"},
            )

        responses = await asyncio.gather(*[leave_request() for _ in range(10)])
        status_codes = [r.status_code for r in responses]

        assert 204 in status_codes
        assert all(code in (204, 400, 403, 404) for code in status_codes)


@pytest.mark.asyncio
async def test_group_revocation_stops_ws_broadcasts(multi_worker_server, user_factory):
    """Confirms group membership revocation halts subsequent WebSocket broadcasts to the removed user."""
    server_url = multi_worker_server
    ws_url = server_url.replace("http://", "ws://") + "/ws"

    owner = await user_factory()
    member = await user_factory()

    async with httpx.AsyncClient(base_url=server_url) as http_client:
        await _establish_friendship(http_client, owner, member)

        create_res = await http_client.post(
            "/groups",
            json={"name": "Eviction Group"},
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )
        group_id = create_res.json()["group_id"]

        await http_client.post(
            f"/groups/{group_id}/members",
            json={"user_id": str(member.user.user_id)},
            headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
        )

    async with websockets.connect(f"{ws_url}?token={member.tokens.access_token}") as member_ws:
        async with httpx.AsyncClient(base_url=server_url) as http_client:
            leave_res = await http_client.delete(
                f"/groups/{group_id}/members/{member.user.user_id}",
                headers={"Authorization": f"Bearer {member.tokens.access_token}"},
            )
            assert leave_res.status_code == 204

            leave_raw = await asyncio.wait_for(member_ws.recv(), timeout=3.0)
            leave_event = json.loads(leave_raw)
            assert leave_event["event"] == "group_membership"
            assert leave_event["group_id"] == str(group_id)

            await http_client.post(
                f"/messages/groups/{group_id}",
                json={"content": "Should not receive"},
                headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
            )

            await http_client.post(
                "/messages/direct",
                json={
                    "recipient_id": str(member.user.user_id),
                    "content": "Direct verification",
                },
                headers={"Authorization": f"Bearer {owner.tokens.access_token}"},
            )

        raw = await asyncio.wait_for(member_ws.recv(), timeout=3.0)
        event = json.loads(raw)
        assert event["event"] == "direct_message"
        assert event["content"] == "Direct verification"
