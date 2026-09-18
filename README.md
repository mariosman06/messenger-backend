# Messenger Backend

Real-time messaging service built with Python 3.13, FastAPI, PostgreSQL, and Redis. Supports multi-worker horizontal scaling, direct and group messaging, active presence tracking, local connection multiplexing, and ultra-fast distributed auth caching.

---

### Tech Stack

| Layer | Technology | Role & Key Details |
| --- | --- | --- |
| **API & WebSockets** | FastAPI (Python 3.13) | REST API endpoints and stateful WebSocket connections |
| **Database** | PostgreSQL 16 (`asyncpg`) | Parameterized SQL execution with connection pooling and explicit transaction lifecycles |
| **Messaging & Presence** | Redis 7 (Pub/Sub) | Inter-worker message broadcasting across distributed nodes and atomic presence counters |
| **State Consistency** | Redis 7 (Streams) | Guaranteed-delivery event logs for cross-worker local cache invalidation |
| **Authentication** | Argon2id + TTLCache | Worker-local memory caching for 0ms token validation, backed by Postgres |
| **Tooling** | Docker, `just`, `uv` | Multi-container runtime, task runner, and dependency management |

---

### System Architecture & Event Flows

#### 1. Fast-Path Auth Validation & Distributed Invalidation

To prevent the database from being bottlenecked by token validation queries on every HTTP request, workers maintain a fast-path local memory cache. 

To eliminate read-after-write race conditions, the system uses a **Hybrid Consistency Model**: When a user logs out, the processing worker *synchronously* evicts the token from its own RAM (Strong Consistency) before broadcasting a Redis Stream event to all *other* workers to do the same (Eventual Consistency).

```text
[ API Request ]
       │
 ┌─────▼─────────────────────────────────────────────────────────────┐
 │ 1. Local Cache Lookup (Fast Path - 0.00ms):                       │
 │    └── Found? ──(Yes)──► Return Authorized User                   │
 │                   │                                               │
 │                 (No)                                              │
 │                   ▼                                               │
 │ 2. Database Lookup (Slow Path - 2.00ms):                          │
 │    ├── Validate against PostgreSQL                                │
 │    └── Store in Local Memory Cache                                │
 └───────────────────────────────────────────────────────────────────┘

[ Logout / Password Change Request ]
       │
 ┌─────▼─────────────────────────────────────────────────────────────┐
 │ 1. Database Transaction:                                          │
 │    └── Revoke tokens or hash new password in PostgreSQL           │
 │                                                                   │
 │ 2. Synchronous Local Eviction (Strong Consistency):               │
 │    └── Instantly drop token from THIS worker's RAM                │
 │                                                                   │
 │ 3. Cache Invalidation Dispatch (Eventual Consistency):            │
 │    └── Publish 'TokenRevoked' event to Redis Stream               │
 └─────┬─────────────────────────────────────────────────────────────┘
       │
       ▼
[ Redis System Events Stream ]
       │
       ├──────────────────────────────────────────┐
       ▼                                          ▼
 ┌─────────────────────────┐            ┌─────────────────────────┐
 │    Worker Instance B    │            │    Worker Instance C    │
 │   (Stream Subscriber)   │            │   (Stream Subscriber)   │
 │                         │            │                         │
 │  Evict User/Tokens      │            │  Evict User/Tokens      │
 │  from Local TTLCache    │            │  from Local TTLCache    │
 └─────────────────────────┘            └─────────────────────────┘

```

#### 2. Message Write & WebSocket Fanout Flow

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
│    ├── Validate Relationship / Membership Permissions                          │
│    └── Persist Message Record & Return Payload                                 │
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

#### 3. Worker In-Memory Socket Registry & Routing

Each worker maintains isolated, in-memory state mappings to route messages to connected clients in $O(1)$ time, eliminating database queries during broadcast delivery.

```text
                             Worker Memory Space
┌───────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│  Fast-Path Auth Cache:     Token Hash ──► Authenticated User Record           │
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

#### 4. Connection Lifecycle & Group Synchronization Flow

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
│   ├── api/              # API routers, local cache, and dependencies
│   ├── config/           # App configuration and logger initialization
│   ├── crypto/           # Password hashing offload and JWT logic
│   ├── database/         # Connection pooling, SQL queries, and models
│   ├── redis/            # Streams/PubSub background listeners & presence
│   ├── services/         # Domain business logic (auth, messages, sockets)
│   ├── utils/            # Non-blocking task spawning and helpers
│   └── main.py           # FastAPI entrypoint and startup lifespan
└── tests/
    ├── e2e/              # Multi-worker process synchronization tests
    ├── integration/      # REST endpoint and WebSocket integration tests
    └── load/             # Locust scenario definitions

```
