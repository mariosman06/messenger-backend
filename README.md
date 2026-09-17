# Messenger Backend

Real-time messaging service built with Python 3.13, FastAPI, PostgreSQL, and Redis. Supports multi-worker horizontal scaling, direct and group messaging, active presence tracking, and local connection multiplexing.

---

### Tech Stack

| Layer | Technology | Role & Key Details |
| --- | --- | --- |
| **API & WebSockets** | FastAPI (Python 3.13) | REST API endpoints and stateful WebSocket connections |
| **Database** | PostgreSQL 16 (`asyncpg`) | Parameterized SQL execution with connection pooling and explicit transaction lifecycles |
| **Pub/Sub & Presence** | Redis 7 | Inter-worker message broadcasting across distributed nodes and atomic presence counters |
| **Authentication** | Argon2id + JWT | Offloaded password hashing via worker thread pools and stateless bearer token authentication |
| **Tooling** | Docker, `just`, `uv` | Multi-container runtime, task runner, and dependency management |

---

### System Architecture & Event Flows

#### 1. Message Write & WebSocket Fanout Flow

When a client sends a message via the REST API, authorization checks and database persistence execute within an isolated database transaction. Once committed, the message payload is dispatched asynchronously to a distributed message bus, broadcasting the event across all active worker instances.

```text
[ Sender Client ]
       │
  POST Message (Direct or Group)
       │
[ API Router ]
       │
┌──────▼─────────────────────────────────────────────────────────────────────────┐
│ Service Layer                                                                  │
│                                                                                │
│ 1. Database Transaction:                                                       │
│    ├── Validate Relationship / Membership Permissions                         │
│    └── Persist Message Record & Return Payload                                │
│                                                                                │
│ 2. Background Dispatch:                                                        │
│    └── Publish Event Payload to Distributed Message Bus                        │
└──────┬──────────────────────────────────┬──────────────────────────────────────┘
       │                                  │
       │ HTTP 201 Response                │ Broadcast Message Event
       ▼                                  ▼
[ Sender Client Response ]         [ Redis Pub/Sub Bus ]
                                          │
                  ┌───────────────────────┴───────────────────────┐
                  │ Broadcast Payload to All Worker Instances     │
                  ▼                                               ▼
      ┌─────────────────────────┐                     ┌─────────────────────────┐
      │     Worker Instance A   │                     │     Worker Instance B   │
      │    (Event Subscriber)   │                     │    (Event Subscriber)   │
      └───────────┬─────────────┘                     └───────────┬─────────────┘
                  │                                               │
         Resolve Target Sockets                          Resolve Target Sockets
         in Local Memory Registry                        in Local Memory Registry
                  │                                               │
           Sockets Found?                                  Sockets Found?
             /        \                                      /        \
          (Yes)       (No)                                (Yes)       (No)
           /            \                                  /            \
  Parallel Delivery    Ignore                     Parallel Delivery    Ignore
  with Timeout                                    with Timeout
         │                                               │
         ▼                                               ▼
[ Recipient Client WS ]                         [ Recipient Client WS ]
```

---

#### 2. Worker In-Memory Socket Registry & Routing

Each worker maintains isolated, in-memory state mappings to route messages to connected clients in $O(1)$ time, eliminating database queries during broadcast delivery.

```text
                             Worker Memory Space
┌───────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│  User Socket Registry:     User ID  ──► Set of Active WebSocket Connections   │
│                                                                               │
│  Group Membership Cache:   Group ID ──► Set of Connected Member User IDs      │
│                                                                               │
│  Reverse Group Lookup:     User ID  ──► Set of Subscribed Group IDs           │
│                                                                               │
│  Concurrency Control:      User ID  ──► Connection Mutex                      │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

#### 3. Connection Lifecycle & Group Synchronization Flow

When a client establishes a WebSocket connection:
1. The worker acquires a per-user concurrency lock to ensure thread-safe state modification.
2. The socket is added to the local user socket registry.
3. The user's active session counter is incremented in the distributed cache.
4. The user's group memberships are queried from the database and cached in worker memory.

On disconnect, the socket is evicted. If no remaining active sockets exist for that user on the worker, the local group mappings are cleared and the distributed session counter is decremented.

```text
[ Client Connect ]
        │
  Establish Session
        │
  ┌─────▼─────────────────────────────────────────────┐
  │ Acquire User Mutex:                               │
  │   1. Register Socket in Local Registry            │
  │   2. Increment Distributed Session Counter        │
  └─────┬─────────────────────────────────────────────┘
        │
  Fetch Active Group Memberships from Database
        │
  ┌─────▼─────────────────────────────────────────────┐
  │ Acquire User Mutex:                               │
  │   Populate Local Group Membership Registries      │
  └───────────────────────────────────────────────────┘

[ Client Disconnect ]
        │
  Terminate Session
        │
  ┌─────▼─────────────────────────────────────────────┐
  │ Acquire User Mutex:                               │
  │   1. Evict Socket from Local Registry             │
  │   2. If Final User Session Closed:                │
  │      - Clear Local Group Membership Registries    │
  │      - Decrement Distributed Session Counter      │
  └───────────────────────────────────────────────────┘
```

---

### Quickstart

1. Copy the example configuration:
   ```bash
   cp config/messenger.yaml.example config/messenger.yaml
   ```

2. Start the service stack:
   ```bash
   docker compose up --build -d
   ```

OpenAPI documentation is available at `http://localhost:8000/docs` (or the configured host/port defined in `config/messenger.yaml`).

---

### Developer Commands (`justfile`)

```bash
just check       # Format and lint code via Ruff
just test        # Run unit, integration, and e2e multi-worker tests
just load-test   # Run Locust load testing scenarios
```

---

### Project Structure

```text
.
├── config/               # App and database configuration files
├── docker-compose.yml    # Service definitions (API workers, Postgres, Redis)
├── Dockerfile            # Container build specification using uv
├── justfile              # Shortcut tasks for testing and formatting
├── pyproject.toml        # Dependencies and tool settings
├── src/
│   ├── api/              # API routers, Pydantic schemas, and dependencies
│   ├── config/           # App configuration and logger initialization
│   ├── crypto/           # Password hashing offload and JWT logic
│   ├── database/         # Connection pooling, SQL queries, and models
│   ├── redis/            # Pub/Sub background listener and presence logic
│   ├── services/         # Domain business logic (messages, sockets)
│   ├── utils/            # Non-blocking task spawning and helpers
│   └── main.py           # FastAPI entrypoint and startup lifespan
└── tests/
    ├── e2e/              # Multi-worker process synchronization tests
    ├── integration/      # REST endpoint and WebSocket integration tests
    └── load/             # Locust scenario definitions
```
