# Local Delivery MVP

[![CI](https://github.com/iliazlobin/sd-local-delivery-backend-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/iliazlobin/sd-local-delivery-backend-mvp/actions/workflows/ci.yml)

REST API for a local-delivery platform. Customers browse a convenience-store catalog at their nearest micro-fulfillment center (DC), search products, place orders with atomic inventory reservation, and track order status. Single-DC MVP deployment.

- **Stack:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · Docker Compose
- **Design:** [DESIGN.md](DESIGN.md)
- **Spec:** [SPEC.md](SPEC.md)

## Quickstart

```bash
# Clone
git clone https://github.com/iliazlobin/sd-local-delivery-backend-mvp.git
cd sd-local-delivery-backend-mvp

# Start the stack
docker compose up --build -d

# Verify it's alive
curl http://localhost:8010/healthz
# → {"status":"ok"}

# Seed test data (2 DCs, 40 products each)
docker compose exec app python scripts/seed.py

# Try an endpoint
curl "http://localhost:8010/v1/dc/lookup?lat=39.95&lon=-75.16"
# → {"dc_id":"PHL-01","name":"Philadelphia Center City","center_lat":39.9526,"center_lon":-75.1652,"distance_mi":0.65}
```

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/healthz` | Health check |
| `GET` | `/v1/dc/lookup?lat=<lat>&lon=<lon>` | Find nearest active DC within delivery radius |
| `GET` | `/v1/catalog?dc_id=<id>&category=<cat>&q=<query>&page=1&page_size=30` | Browse/search products with availability |
| `POST` | `/v1/orders` | Create order with atomic inventory reservation (idempotent on `order_id`) |
| `GET` | `/v1/orders/{order_id}` | Get order status and line items |
| `POST` | `/v1/orders/{order_id}/status` | Advance order through lifecycle |
| `POST` | `/v1/orders/{order_id}/cancel` | Cancel order and release reservations |
| `POST` | `/v1/admin/sweep-reservations` | Expire orders in `confirmed` > 15 min |

Full request/response shapes in [DESIGN.md §6](DESIGN.md#6-api-contracts).

### Order creation

```bash
# Create an order (uses catalog-discovered product IDs)
PRODUCT_ID=$(curl -s "http://localhost:8010/v1/catalog?dc_id=PHL-01&page=1&page_size=1" | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['product_id'])")
ORDER_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

curl -s -X POST http://localhost:8010/v1/orders \
  -H "Content-Type: application/json" \
  -d "{
    \"dc_id\": \"PHL-01\",
    \"items\": [{\"product_id\": \"$PRODUCT_ID\", \"quantity\": 1}],
    \"delivery_address\": \"123 Market St, Philadelphia, PA 19106\",
    \"order_id\": \"$ORDER_ID\"
  }"
# → 201 {"order_id":"...","status":"confirmed","items":[...],"total_amount_cents":...}
```

### Order lifecycle

```bash
# Track the order
curl -s http://localhost:8010/v1/orders/$ORDER_ID | python3 -m json.tool

# Advance status (confirmed → picking → packed → en_route → delivered)
curl -s -X POST http://localhost:8010/v1/orders/$ORDER_ID/status \
  -H "Content-Type: application/json" \
  -d '{"status": "picking"}'

# Cancel (only in confirmed or picking)
curl -s -X POST http://localhost:8010/v1/orders/$ORDER_ID/cancel
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8010` | Host port the app service is published on |
| `DATABASE_URL` | `postgresql+asyncpg://local_delivery:local_delivery@localhost:5432/local_delivery` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Internal server port |
| `LOG_LEVEL` | `info` | Uvicorn log level |

Override via `.env` file or environment variables. See `.env.example` for the defaults.

```bash
# Run on a custom port
APP_PORT=8020 docker compose up -d
```

## Testing

### White-box (unit + functional)

```bash
pip install -e ".[dev]"
pytest tests/unit/ -v
pytest tests/functional/ -v
```

### Black-box acceptance

Runs against a live, seeded instance at `API_BASE_URL`. These tests speak HTTP only — they never import the app.

```bash
# Default port
API_BASE_URL=http://localhost:8010 pytest verify/acceptance/ -v

# Custom port
API_BASE_URL=http://localhost:8020 pytest verify/acceptance/ -v
```

### All layers together

```bash
pip install -e ".[dev]"
pytest tests/unit/ tests/functional/ -v
API_BASE_URL=http://localhost:8010 pytest verify/acceptance/ -v
```

## Architecture

```
Client (REST)
  │
  ▼
FastAPI (app:8000)         ← routers → services → models/schemas
  │            │
  ▼            ▼
PostgreSQL 16   Redis 7
(all data)      (availability cache, 60s TTL)
```

- **Routers** are thin — HTTP parsing and validation only.
- **Services** contain all business logic: Haversine DC lookup, catalog browse/search with availability merge, order creation with pessimistic `SELECT ... FOR UPDATE` row-locking, status lifecycle enforcement, reservation sweep.
- **Models** are SQLAlchemy ORM classes (DC, Product, Inventory, Order, OrderLineItem).
- **Schemas** are Pydantic DTOs for request/response serialization.

## Project layout

```
├── src/local_delivery/       # Application package
│   ├── main.py               # FastAPI app factory + lifespan + /healthz
│   ├── config.py             # pydantic-settings
│   ├── db.py                 # async session dependency
│   ├── redis.py              # Redis client dependency
│   ├── routers/              # dc, catalog, orders, admin
│   ├── services/             # dc, catalog, order, inventory
│   ├── models/               # ORM models
│   └── schemas/              # Pydantic DTOs
├── alembic/                  # Database migrations
├── scripts/seed.py           # Seed DCs, products, inventory
├── tests/                    # White-box tests (unit + functional)
├── verify/acceptance/        # Black-box acceptance suite
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── DESIGN.md                 # Architecture & design spec
├── SPEC.md                   # Build spec (functional requirements)
└── DEPLOY.md                 # Deployment guide
```

## Limitations (MVP)

- **Single-DC.** Only one DC is queried per request. Multi-DC catalog aggregation and routing are deferred.
- **No real payment.** Orders are confirmed without payment authorization. The `user_id` field is a placeholder.
- **PostgreSQL ILIKE search.** Full-text relevance ranking, typo tolerance, and faceted search require Elasticsearch (out of scope for MVP).
- **Haversine distance only.** Drive-time routing (OSRM) is deferred. DC lookup uses straight-line distance.
- **Polling for status.** No SSE or WebSocket push. Clients poll `GET /v1/orders/{id}` for updates.
- **Manual reservation sweep.** The sweep endpoint is a one-shot POST. A background cron/scheduler is deferred.
- **No authentication.** Admin endpoints are unauthenticated. All endpoints are open.
- **Inventory cache staleness.** Redis availability cache has a 60-second TTL. Order creation always checks the transactional DB — the cache is for browse accuracy only.
