# Messenger Backend

A modular, high-performance real-time messaging backend API built with Python, FastAPI, raw SQL via `asyncpg`, and Redis Pub/Sub. Designed around Domain-Driven Design (DDD) principles to power real-time direct messaging, group chats, social graph management, and WebSocket push notifications.

---

## Features

* **Real-time Push Notifications:** WebSockets integrated with Redis Pub/Sub for horizontally scalable event broadcasting.
* **Direct & Group Messaging:** Complete conversation lifecycle management, historical pagination, and authorization checks.
* **Social Graph Management:** Granular friendship request handling and group access control.
* **High-Performance Async I/O:** Built with raw SQL queries via `asyncpg` for maximum throughput and low latency without ORM overhead.
* **Robust Error Handling & Reliability:** Native connection pooling for both PostgreSQL and Redis with automated health checks (`PING`).

---

## Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Async ASGI)
* **Real-time Messaging:** WebSockets + [Redis Pub/Sub](https://redis.io/)
* **Database & Driver:** PostgreSQL 16 with [asyncpg](https://github.com/MagicStack/asyncpg) (Raw SQL execution with custom connection pooling)
* **Validation & Settings:** [Pydantic v2](https://docs.pydantic.dev/) & Pydantic Settings
* **Package Management:** [uv](https://github.com/astral-sh/uv) (Ultra-fast Python package installer)
* **Testing & Mocks:** Pytest, Asyncio Pytest, HTTPX AsyncClient
* **Task Runner:** [just](https://github.com/casey/just)
* **Containerization:** Docker & Docker Compose

---

## Architecture Flow

```text
[ Client ] <--- WebSocket ---> [ FastAPI Server ] <--- Pub/Sub ---> [ Redis Cluster ]
                                      |
                                  asyncpg
                                      |
                                      v
                                [ PostgreSQL ]
```

1. **HTTP Endpoints:** Handle state changes (e.g., sending messages, leaving groups, accepting friend requests).
2. **Database:** Operations execute inside ACID-compliant PostgreSQL transactions using explicit SQL queries.
3. **Redis Pub/Sub:** Dispatches internal event payloads across instances to target active WebSocket subscribers instantly.

---

## Getting Started

### Prerequisites

* [Docker](https://www.docker.com/) & Docker Compose
* [uv](https://github.com/astral-sh/uv) (for local development)
* [just](https://github.com/casey/just) (optional, command runner)

### Environment Configuration

Copy the sample environment file and update your configuration if needed:

```bash
cp config/messenger.yaml.example config/messenger.yaml
```

### Running with Docker Compose

Start the database, Redis, and API services:

```bash
docker compose up -d --build
```

The API will be available at `http://localhost:8000` (Interactive docs at `/docs`).

---

## Local Development & Testing

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Run tests:**
   Using `just`:
   ```bash
   just test
   ```
   Or directly with `pytest`:
   ```bash
   uv run pytest
   ```

---

## Project Structure

```text
.
├── config/             # Environment configuration files
├── src/
│   ├── api/            # FastAPI routes, dependencies, and WS endpoints
│   ├── database/       # Connection pooling, raw SQL queries, and models
│   ├── redis/          # Connection management, event schemas, and Pub/Sub
│   └── services/       # Domain logic (auth, friendships, groups, messages, WS)
├── tests/              # Integration and unit test suites
├── docker-compose.yml
├── justfile
└── pyproject.toml
```
