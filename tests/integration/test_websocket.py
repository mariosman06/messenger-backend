import asyncio
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.websockets import WebSocketDisconnect

import src.services.websocket as websocket_service
from tests.conftest import websocket_connect
from tests.factories import TestUser


@pytest.mark.asyncio
async def test_websocket_auth_handshake(user_factory):
    """Tests authentication enforcement during the WebSocket handshake."""
    user: TestUser = await user_factory()

    # Rejects connection attempt missing token query param
    with pytest.raises(WebSocketDisconnect):
        async with websocket_connect("/ws"):
            pass

    # Rejects connection attempt with invalid token
    with pytest.raises(WebSocketDisconnect):
        async with websocket_connect("/ws?token=invalid_token"):
            pass

    # Accepts connection attempt with valid token
    async with websocket_connect(f"/ws?token={user.tokens.access_token}") as ws:
        assert ws is not None


@pytest.mark.asyncio
async def test_websocket_direct_message_realtime_push(client, user_factory):
    """Tests real-time WebSocket delivery of direct messages to an active recipient session."""
    alice: TestUser = await user_factory(username="alice_ws_dm")
    bob: TestUser = await user_factory(username="bob_ws_dm")

    await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    await client.post(
        f"/friends/requests/{alice.user.user_id}/accept",
        headers=bob.headers,
    )

    async def mock_publish(channel: str, payload: dict):
        await websocket_service._dispatch_local_message(payload)

    with patch.object(websocket_service, "publish_ws_push", side_effect=mock_publish):
        async with websocket_connect(f"/ws?token={bob.tokens.access_token}") as bob_ws:
            send_resp = await client.post(
                "/messages/direct",
                json={
                    "recipient_id": str(bob.user.user_id),
                    "content": "Hello real-time Bob!",
                },
                headers=alice.headers,
            )
            assert send_resp.status_code == 201

            event = await bob_ws.receive_json()
            assert event["event"] == "direct_message"
            assert event["sender_id"] == str(alice.user.user_id)
            assert event["recipient_id"] == str(bob.user.user_id)
            assert event["content"] == "Hello real-time Bob!"


@pytest.mark.asyncio
async def test_websocket_group_message_realtime_push(client, user_factory):
    """Tests single topic group broadcast delivery to active group member connections."""
    alice: TestUser = await user_factory(username="alice_ws_grp")
    bob: TestUser = await user_factory(username="bob_ws_grp")

    create_resp = await client.post(
        "/groups",
        json={"name": "Realtime Devs"},
        headers=alice.headers,
    )
    group_id = create_resp.json()["group_id"]

    await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(bob.user.user_id)},
        headers=alice.headers,
    )

    async def mock_publish(channel: str, payload: dict):
        await websocket_service._dispatch_local_message(payload)

    with patch.object(websocket_service, "publish_ws_push", side_effect=mock_publish):
        async with websocket_connect(f"/ws?token={bob.tokens.access_token}") as bob_ws:
            await asyncio.sleep(0.05)

            msg_resp = await client.post(
                f"/messages/groups/{group_id}",
                json={"content": "Group alert!"},
                headers=alice.headers,
            )
            assert msg_resp.status_code == 201

            event = await bob_ws.receive_json()
            assert event["event"] == "group_message"
            assert event["group_id"] == group_id
            assert event["sender_id"] == str(alice.user.user_id)
            assert event["content"] == "Group alert!"


@pytest.mark.asyncio
async def test_websocket_revoking_group_membership_blocks_pushes(client, user_factory):
    """Verifies revoking local group routing stops push delivery for subsequent group activity."""
    alice: TestUser = await user_factory(username="alice_ws_leave")
    bob: TestUser = await user_factory(username="bob_ws_leave")

    await client.post(
        "/friends/requests",
        json={"addressee_id": str(bob.user.user_id)},
        headers=alice.headers,
    )
    await client.post(
        f"/friends/requests/{alice.user.user_id}/accept",
        headers=bob.headers,
    )

    create_resp = await client.post(
        "/groups",
        json={"name": "Transient Group"},
        headers=alice.headers,
    )
    group_id = UUID(create_resp.json()["group_id"])

    await client.post(
        f"/groups/{group_id}/members",
        json={"user_id": str(bob.user.user_id)},
        headers=alice.headers,
    )

    async def mock_publish(channel: str, payload: dict):
        await websocket_service._dispatch_local_message(payload)

    with patch.object(websocket_service, "publish_ws_push", side_effect=mock_publish):
        async with websocket_connect(f"/ws?token={bob.tokens.access_token}") as bob_ws:
            # Remove Bob via HTTP so both DB and WS in-memory state are updated
            leave_resp = await client.delete(
                f"/groups/{group_id}/members/{bob.user.user_id}",
                headers=bob.headers,
            )
            assert leave_resp.status_code == 204

            # Message sent to group (Bob shouldn't receive this)
            await client.post(
                f"/messages/groups/{group_id}",
                json={"content": "Post-leave message"},
                headers=alice.headers,
            )

            # Direct message sent to Bob (Bob MUST receive this)
            await client.post(
                "/messages/direct",
                json={
                    "recipient_id": str(bob.user.user_id),
                    "content": "Direct verification",
                },
                headers=alice.headers,
            )

            event = await bob_ws.receive_json()
            assert event["event"] == "direct_message"
            assert event["content"] == "Direct verification"
