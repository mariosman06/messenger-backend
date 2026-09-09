# Messenger Backend

![Tests](https://github.com/mariosman06/messenger-backend/actions/workflows/test.yml/badge.svg)
![Code Check](https://github.com/mariosman06/messenger-backend/actions/workflows/code_check.yml/badge.svg)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?style=flat-square&logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)

A modular, high-performance real-time messaging backend API built with Python, FastAPI, raw SQL via `asyncpg`, and Redis. Designed around Domain-Driven Design (DDD) principles to power real-time direct messaging, group chats, social graph management, WebSocket push notifications, and ultra-fast caching.

---

## Features

* **Real-time Push Notifications:** WebSockets integrated with Redis Pub/Sub for horizontally scalable event broadcasting across server instances.
* **High-Performance Caching:** Redis key-value caching for low-latency session validation, route optimization, and state storage.
* **Direct & Group Messaging:** Complete conversation lifecycle management, historical pagination, and membership authorization.
* **Social Graph Management:** Granular friendship request processing and group access control.
* **Raw SQL Performance:** Asynchronous database interaction using `asyncpg` for maximum query execution speed without ORM overhead.
* **Reliable Infrastructure:** Built-in connection pooling for PostgreSQL and Redis with automated initialization `PING` health checks.

---

## Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Async ASGI)
* **Cache & Real-time Messaging:** [Redis](https://redis.io/) (In-memory Caching & Pub/Sub Event Bus)
* **Database & Driver:** PostgreSQL 16 with [asyncpg](https://github.com/MagicStack/asyncpg) (Raw SQL with custom connection pooling)
* **Validation & Settings:** [Pydantic v2](https://docs.pydantic.dev/) & Pydantic Settings
* **Package Management:** [uv](https://github.com/astral-sh/uv) (Ultra-fast Python package installer)
* **Testing & Mocks:** Pytest, Asyncio Pytest, HTTPX AsyncClient
* **Task Runner:** [just](https://github.com/casey/just)
* **Containerization:** Docker & Docker Compose

---

## Architecture Flow

```text
[ Client ] <--- WebSocket ---> [ FastAPI Server ] <--- Caching & Pub/Sub ---> [ Redis ]
                                      |
                                  asyncpg
                                      |
                                      v
                                [ PostgreSQL ]
```

1. **HTTP Endpoints:** Process incoming requests for state changes (e.g., messaging, group modifications, friend requests).
2. **Database:** Operations execute inside ACID-compliant PostgreSQL transactions using explicit SQL queries.
3. **Redis Caching & Pub/Sub:** Serves as a high-speed cache for fast data lookups while broadcasting real-time message events across instances to target active WebSockets instantly.

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
│   ├── redis/          # Connection management, caching queries, event schemas, and Pub/Sub
│   └── services/       # Domain logic (auth, friendships, groups, messages, WS)
├── tests/              # Integration and unit test suites
├── docker-compose.yml
├── justfile
└── pyproject.toml
```
