# Deployment Guide

## Prerequisites

- **Docker** (20.10+) and **Docker Compose** (v2, the `docker compose` plugin)
- **curl** for health checks
- **Python 3.12+** and **pip** (for local development only)
- An available host port (default: `8010`)

> **Port conflicts:** The default `APP_PORT=8010` avoids collisions with common services (5432/Postgres, 6379/Redis, 8000/8080). If 8010 is taken, set `APP_PORT` in `.env` or on the command line.

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/iliazlobin/sd-local-delivery-backend-mvp.git
cd sd-local-delivery-backend-mvp
```

### 2. Configure (optional)

```bash
cp .env.example .env
# Edit .env to customize APP_PORT or other settings
```

### 3. Start the stack

```bash
docker compose up --build -d
```

This builds the application image, starts PostgreSQL 16 and Redis 7, waits for both to become healthy, runs Alembic migrations, and launches the API server on `http://localhost:8010`.

### 4. Verify the deployment

```bash
# Health check
curl -sf http://localhost:8010/healthz
# Expected: {"status":"ok"}

# Check service status
docker compose ps
```

### 5. Seed test data (optional)

```bash
# Seed DCs, products, and inventory into the running database
docker compose exec app python scripts/seed.py
```

### 6. Run tests

```bash
# Unit tests (no Docker needed)
pip install -e ".[dev]"
pytest tests/unit/ -v

# Functional tests (in-process, needs a database)
pytest tests/functional/ -v

# Black-box acceptance tests (against the running container)
API_BASE_URL=http://localhost:8010 pytest verify/acceptance/ -v
```

### 7. Stop the stack

```bash
# Stop containers (preserve data)
docker compose down

# Stop and delete volumes (fresh start)
docker compose down -v
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8010` | Host port the app service is published on |
| `DATABASE_URL` | `postgresql+asyncpg://local_delivery:local_delivery@localhost:5432/local_delivery` | PostgreSQL connection string (asyncpg driver) |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Internal server port |
| `LOG_LEVEL` | `info` | Uvicorn log level |

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   app:8000   │────▶│  db:5432     │     │ redis:6379   │
│  (FastAPI)   │     │ (PostgreSQL) │     │   (Redis)    │
└──────────────┘     └──────────────┘     └──────────────┘
       │
  ${APP_PORT}:8000
       │
   localhost:8010
```

The `app` service depends on `db` and `redis` being healthy before starting. It runs `alembic upgrade head` to apply migrations, then starts the uvicorn server. Only the `app` port is published to the host; `db` and `redis` communicate over the internal compose network.

## Troubleshooting

**Port conflict:** If port 8010 is in use:
```bash
APP_PORT=8020 docker compose up -d
```

**Database connection refused:** Check that the `db` service is healthy:
```bash
docker compose ps db
```

**Migrations failed:** View app logs:
```bash
docker compose logs app
```

**Fresh start (reset all data):**
```bash
docker compose down -v
docker compose up --build -d
```
