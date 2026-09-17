from gevent import monkey

monkey.patch_all()

# ruff: noqa: E402

import json
import secrets
import string
import time
from urllib.parse import urlparse

import gevent
import requests
import websocket
from gevent.event import Event
from gevent.pool import Group
from gevent.queue import Empty, Queue
from locust import FastHttpUser, between, events, runners, task

PREPARED_USER_PAIRS = Queue()
DEFAULT_PRE_REGISTER = 3000
DEFAULT_WS_TIMEOUT = 3.0
DEFAULT_POLL_INTERVAL = 0.05
DEFAULT_PASSWORD = "SecurePassword123!"


@events.init_command_line_parser.add_listener
def register_custom_arguments(parser):
    """Registers custom CLI flags passed directly from CLI / Justfile."""
    parser.add_argument(
        "--pre-register",
        type=int,
        default=DEFAULT_PRE_REGISTER,
        help="Number of user pairs to pre-register before starting the load test",
    )


def derive_ws_url(http_host: str) -> str:
    """Converts standard HTTP/HTTPS host targets to WS/WSS URL endpoints."""
    parsed = urlparse(http_host)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc or parsed.path
    return f"{scheme}://{netloc}/ws"


def extract_event_name(data: dict) -> str:
    """Parses event names, mapping group membership actions to expected scenario states."""
    evt = data.get("event") or data.get("type", "unknown")
    if evt == "group_membership":
        action = str(data.get("action", "")).upper()
        if action == "JOIN":
            return "group_joined"
        if action == "LEAVE":
            return "group_left"
    return evt


def random_string(length=8):
    """Generate a random lowercase alphanumeric string of specified length."""
    return "".join(
        secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )


def register_single_user(host, prefix):
    """Register a single new user on the target REST API host."""
    payload = {
        "username": f"{prefix}_{random_string()}",
        "password": DEFAULT_PASSWORD,
    }
    try:
        res = requests.post(f"{host}/auth/register", json=payload, timeout=20)
        if res.status_code == 201:
            data = res.json()
            return {
                "token": data["tokens"]["access_token"],
                "userId": data["user"]["user_id"],
            }
    except Exception as e:
        print(f"[ERROR] Pre-registration failed: {e}")
    return None


def provision_pair(host, index):
    """Register a pair of users and push them onto the pre-registration queue."""
    user_a = register_single_user(host, f"pre_a_{index}")
    user_b = register_single_user(host, f"pre_b_{index}")
    if user_a and user_b:
        PREPARED_USER_PAIRS.put_nowait((user_a, user_b))


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    """Concurrently pre-register user pairs into the pool using CLI arguments."""
    if isinstance(environment.runner, runners.WorkerRunner):
        return

    host = environment.host or "http://127.0.0.1:8008"
    count = (
        environment.parsed_options.pre_register
        if environment.parsed_options and environment.parsed_options.pre_register
        else DEFAULT_PRE_REGISTER
    )

    print(
        f"\n[SETUP] Pre-registering {count} user pairs concurrently on target host {host}..."
    )
    group = Group()
    for i in range(1, count + 1):
        group.spawn(provision_pair, host, i)
    group.join()
    print(f"[SETUP] Setup complete! {PREPARED_USER_PAIRS.qsize()} user pairs ready in pool.\n")


class HTTPTriggerUser(FastHttpUser):
    """CPU-optimized Locust user using C-backed geventhttpclient."""

    weight = 4
    wait_time = between(1, 2)

    network_timeout = DEFAULT_WS_TIMEOUT
    connection_timeout = DEFAULT_WS_TIMEOUT

    def listen_and_verify(self, ws, received_events, stop_event):
        """Continuously receive WebSocket messages in a background greenlet until stopped."""
        while not stop_event.is_set():
            try:
                raw_data = ws.recv()
                recv_timestamp = time.time()
                if raw_data:
                    data = json.loads(raw_data)
                    received_events.append({"data": data, "recv_time": recv_timestamp})

                    evt_name = extract_event_name(data)
                    events.request.fire(
                        request_type="WS_EVT",
                        name=f"evt_{evt_name}",
                        response_time=0,
                        response_length=len(raw_data),
                        exception=None,
                        context={},
                    )
            except (TimeoutError, websocket.WebSocketTimeoutException):
                gevent.sleep(DEFAULT_POLL_INTERVAL)
                continue
            except (
                websocket.WebSocketConnectionClosedException,
                ConnectionResetError,
                OSError,
            ):
                break
            except Exception:
                gevent.sleep(DEFAULT_POLL_INTERVAL)
                continue

    @task
    def http_trigger_scenario(self):
        """Execute user lifecycle tasks and verify incoming WebSocket event ordering."""
        base_host = self.host or "http://127.0.0.1:8008"
        ws_endpoint = derive_ws_url(base_host)

        user_pair_from_queue = True
        try:
            user_a, user_b = PREPARED_USER_PAIRS.get_nowait()
        except Empty:
            user_pair_from_queue = False
            res_a = self.client.post(
                "/auth/register",
                json={
                    "username": f"dyn_a_{random_string()}",
                    "password": DEFAULT_PASSWORD,
                },
                name="/auth/register (dynamic)",
            )
            res_b = self.client.post(
                "/auth/register",
                json={
                    "username": f"dyn_b_{random_string()}",
                    "password": DEFAULT_PASSWORD,
                },
                name="/auth/register (dynamic)",
            )
            if res_a.status_code != 201 or res_b.status_code != 201:
                return
            user_a = {
                "token": res_a.json()["tokens"]["access_token"],
                "userId": res_a.json()["user"]["user_id"],
            }
            user_b = {
                "token": res_b.json()["tokens"]["access_token"],
                "userId": res_b.json()["user"]["user_id"],
            }

        headers_a = {"Authorization": f"Bearer {user_a['token']}"}
        headers_b = {"Authorization": f"Bearer {user_b['token']}"}

        ws_b_url = f"{ws_endpoint}?token={user_b['token']}"
        start_time = time.time()
        ws_b = None
        listener_greenlet = None
        received_events = []
        stop_listener = Event()

        try:
            ws_b = websocket.create_connection(ws_b_url, timeout=2.0)
            ws_b.settimeout(0.5)
            events.request.fire(
                request_type="WS",
                name="ws_connect",
                response_time=int((time.time() - start_time) * 1000),
                response_length=0,
                exception=None,
                context={},
            )
            listener_greenlet = gevent.spawn(
                self.listen_and_verify, ws_b, received_events, stop_listener
            )
        except Exception as e:
            events.request.fire(
                request_type="WS",
                name="ws_connect",
                response_time=int((time.time() - start_time) * 1000),
                response_length=0,
                exception=e,
                context={},
            )
            if user_pair_from_queue:
                PREPARED_USER_PAIRS.put_nowait((user_a, user_b))
            return

        try:
            # 1. Profile Check
            self.client.get("/auth/me", headers=headers_a, name="/auth/me")

            # 2. Friend Request Flow
            req_res = self.client.post(
                "/friends/requests",
                json={"addressee_id": user_b["userId"]},
                headers=headers_a,
                name="/friends/req",
            )
            if req_res.status_code == 201:
                self.client.post(
                    f"/friends/requests/{user_a['userId']}/accept",
                    headers=headers_b,
                    name="/friends/accept",
                )

            # 3. Group Setup
            group_res = self.client.post(
                "/groups",
                json={"name": f"Group_VU_{random_string(6)}"},
                headers=headers_a,
                name="/groups",
            )
            if group_res.status_code == 201:
                group_id = group_res.json().get("group_id")

                self.client.post(
                    f"/groups/{group_id}/members",
                    json={"user_id": user_b["userId"]},
                    headers=headers_a,
                    name="/groups/add_mem",
                )

                # 4. Messages
                target_group_msg = f"Group chat ping {random_string(4)}"
                self.client.post(
                    f"/messages/groups/{group_id}",
                    json={"content": target_group_msg},
                    headers=headers_a,
                    name="/messages/group",
                )

                target_dm_content = f"Direct message ping {random_string(4)}"
                self.client.post(
                    "/messages/direct",
                    json={"recipient_id": user_b["userId"], "content": target_dm_content},
                    headers=headers_a,
                    name="/messages/direct",
                )

                # 5. Teardown Group
                self.client.delete(
                    f"/groups/{group_id}/members/{user_b['userId']}",
                    headers=headers_b,
                    name="/groups/rm_mem",
                )

            # 6. Teardown Friendship
            self.client.delete(
                f"/friends/{user_b['userId']}", headers=headers_a, name="/friends/{target_id}"
            )

            # Await incoming WS events
            expected_order = ["group_joined", "group_message", "direct_message", "group_left"]
            timeout_limit = time.time() + DEFAULT_WS_TIMEOUT
            while len(received_events) < len(expected_order) and time.time() < timeout_limit:
                gevent.sleep(DEFAULT_POLL_INTERVAL)

            received_names = [extract_event_name(item["data"]) for item in received_events]

            # Order-preserving subsequence verification
            iter_received = iter(received_names)
            is_valid_order = all(expected in iter_received for expected in expected_order)

            events.request.fire(
                request_type="ASSERT",
                name="seq_order",
                response_time=0,
                response_length=0,
                exception=None
                if is_valid_order
                else AssertionError(
                    f"Got {received_names}, expected subsequence {expected_order}"
                ),
                context={},
            )
        finally:
            stop_listener.set()

            if listener_greenlet:
                gevent.kill(listener_greenlet)
                listener_greenlet.join(timeout=0.1)

            if ws_b:
                try:
                    ws_b.abort()
                except Exception as e:
                    print(f"[DEBUG] Failed to abort WebSocket connection cleanly: {e}")

            if user_pair_from_queue:
                PREPARED_USER_PAIRS.put_nowait((user_a, user_b))
