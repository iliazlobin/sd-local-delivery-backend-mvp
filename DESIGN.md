# Local Delivery MVP — Design

> **Stack:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · SQLAlchemy (async) · Alembic · pytest · httpx · Docker Compose
> **Architecture:** Monolithic REST API — PostgreSQL for source-of-truth, Redis for availability cache.

## 1. Overview

A local-delivery platform where customers browse a convenience-store catalog at their nearest micro-fulfillment center (DC), search products, place orders with atomic inventory reservation, and track order status. This MVP targets the core ordering path on a single-DC deployment.

The broader target (deferred past MVP) covers 500 DCs across US metros, Elasticsearch-backed full-text search, OSRM drive-time routing, Kafka/outbox-based event choreography, SSE push for order tracking, substitution recommendations, re-order from history, and real payment integration.

## 2. Scope

### In scope

- FR1 — DC geo-lookup (Haversine), nearest active DC within delivery radius
- FR2 — Category browse with real-time availability at a DC
- FR3 — Text search (PostgreSQL ILIKE) with in-stock-first ordering
- FR4 — Multi-item order creation with pessimistic row-locking, idempotency, partial-stock 409
- FR5 — Order retrieval (polling GET)
- FR6 — Status lifecycle transitions (confirmed → picking → packed → en_route → delivered)
- FR7 — Cancel order (before packing), reservation release
- FR8 — Reservation TTL sweep (15-minute expiry)

### Out of scope

- Substitution recommendations, order history/re-order
- Kafka / outbox pattern — synchronous in-process calls only
- Elasticsearch — PostgreSQL ILIKE for search
- OSRM drive-time routing — Haversine distance only
- SSE push for order tracking — polling GET
- Real payment integration — mock auth
- Multi-DC deployment — single DC for MVP
- Background inventory snapshotter — Redis loaded on-demand

## 3. Architecture

```
Client (REST)
  │
  ▼
FastAPI (app:8000)
  ├── routers/        ← HTTP parsing only, no business logic
  │   ├── dc.py           → GET /v1/dc/lookup
  │   ├── catalog.py      → GET /v1/catalog
  │   ├── orders.py       → POST /v1/orders, GET /v1/orders/{id},
  │   │                      POST /v1/orders/{id}/status,
  │   │                      POST /v1/orders/{id}/cancel
  │   └── admin.py        → POST /v1/admin/sweep-reservations
  │
  ├── services/       ← all business logic + data access
  │   ├── dc_service.py        → Haversine DC lookup
  │   ├── catalog_service.py   → browse + search + availability merge
  │   ├── order_service.py     → create, get, advance status, cancel
  │   └── inventory_service.py → reserve, release, sweep
  │
  ├── models/         ← SQLAlchemy ORM models (DC, Product, Inventory, Order, OrderLineItem)
  ├── schemas/        ← Pydantic request/response DTOs
  ├── config.py       → pydantic-settings (DATABASE_URL, REDIS_URL, APP_PORT)
  ├── db.py           → async session dependency
  ├── redis.py        → Redis client dependency
  └── main.py         → app factory + lifespan + /healthz

PostgreSQL 16          Redis 7
(products, inventory,  (availability snapshots:
 orders, line items)    avail:{dc_id}:{product_id} keys)
```

### Data flows

**DC Lookup (FR1):** `GET /v1/dc/lookup?lat=39.95&lon=-75.16` → DC Service loads all active DCs → Haversine filter within `delivery_radius_mi` → sort by distance → return nearest or 404.

**Catalog browse (FR2):** `GET /v1/catalog?dc_id=PHL-01&category=snacks&page=1` → Catalog Service queries Product table filtered by dc_id + category → fetches availability from Redis (`GET avail:{dc_id}:{product_id}` for each product, with 60s TTL cache) → merges `available_qty` → paginates (30/page) → returns items with `available` bool.

**Text search (FR3):** `GET /v1/catalog?dc_id=PHL-01&q=chips` → Catalog Service runs `SELECT ... WHERE dc_id=$1 AND name ILIKE '%chips%'` → fetches availability from Redis → sorts in-stock first → paginates.

**Order creation (FR4):** `POST /v1/orders {dc_id, items, delivery_address, order_id}` →
1. Validate dc_id exists
2. If order_id exists → return 200 (idempotent)
3. Verify all products exist at DC
4. Open transaction → `SELECT ... FOR UPDATE` on inventory rows in product_id order
5. Check `stock_on_hand - reserved_qty >= qty` for each item
6. If partial → rollback, return 409 with unavailable items
7. If full → increment reserved_qty, INSERT Order + OrderLineItems, commit → return 201

**Status lifecycle (FR6):** Valid transitions form a directed graph: confirmed → picking → packed → en_route → delivered. Cancelled and delivered are terminal states. Skipping a state → 409. Backward transition → 409.

**Reservation sweep (FR8):** `POST /v1/admin/sweep-reservations` → SELECT orders in `confirmed` status with `created_at < NOW() - INTERVAL '15 minutes'` → for each, set status=cancelled, release all reserved_qty → return count.

## 4. Stack & deployment

| Layer | Technology | Rationale |
|---|---|---|
| Runtime | Python 3.12 + FastAPI | Async I/O, pydantic validation, OpenAPI auto-docs |
| ORM | SQLAlchemy 2.0 (async) | Mature, Alembic integration, async session support |
| Database | PostgreSQL 16 | All data: products, inventory, orders; ILIKE for search |
| Cache | Redis 7 | Per-product availability cache: `avail:{dc_id}:{product_id}` with 60s TTL |
| Migrations | Alembic | Versioned schema; one migration for MVP tables |
| Tests | pytest + httpx | Black-box acceptance (verify/) + white-box unit/functional (tests/) |
| Deploy | Docker Compose | `app` + `db` + `redis`; app on `${APP_PORT:-8010}:8000` |
| Config | pydantic-settings | `DATABASE_URL`, `REDIS_URL`, `APP_PORT` via env, typed |

## 5. Data model

### PostgreSQL tables

```
DC
  dc_id: text (PK)               ← short code, e.g. "PHL-01"
  name: text
  center_lat: double
  center_lon: double
  delivery_radius_mi: double
  status: text                   ← active | inactive

Product
  product_id: uuid (PK)
  dc_id: text (FK → DC)
  name: text
  brand: text
  category: text
  unit_price_cents: int
  is_active: boolean
  UNIQUE (dc_id, name)

Inventory
  inventory_id: uuid (PK)
  dc_id: text (FK → DC)
  product_id: uuid (FK → Product)
  stock_on_hand: int             ← physical count at DC
  reserved_qty: int              ← held for active checkouts (default 0)
  version: int                   ← optimistic-concurrency column (default 1)
  UNIQUE (dc_id, product_id)

Order
  order_id: uuid (PK)            ← client-generated UUIDv4 (idempotency key)
  user_id: text                  ← opaque user identifier
  dc_id: text (FK → DC)
  status: text                   ← confirmed | picking | packed | en_route | delivered | cancelled
  total_amount_cents: int
  delivery_address: text
  created_at: timestamp
  updated_at: timestamp

OrderLineItem
  line_item_id: uuid (PK)
  order_id: uuid (FK → Order)
  product_id: uuid (FK → Product)
  quantity: int
  unit_price_cents: int
```

### Indexes

- `inventory(dc_id, product_id)` — unique, used for `FOR UPDATE` lock ordering
- `products(dc_id, name)` — for ILIKE search
- `products(dc_id, category)` — for category browse
- `orders(status, created_at)` — for sweep query

### Redis key patterns

| Key | Type | Content | TTL |
|---|---|---|---|
| `avail:{dc_id}:{product_id}` | String | `available_qty` (int) | 60s |

Availability is computed on cache miss from the transactional DB (`stock_on_hand - reserved_qty`), then cached. Order creation always checks the transactional DB with row locks — the cache is for browse-level accuracy only.

## 6. API contracts

### `GET /healthz`

Health check for Docker compose readiness probe.

- **200** `{"status": "ok"}`

---

### `GET /v1/dc/lookup?lat=<lat>&lon=<lon>`

Find the nearest active DC serving a geographic point.

- **200** — nearest DC found
  ```json
  {
    "dc_id": "PHL-01",
    "name": "Philadelphia Center City",
    "center_lat": 39.9526,
    "center_lon": -75.1652,
    "distance_mi": 1.2
  }
  ```
- **404** `{"detail": "No DC covers this location"}`
- **422** — missing or non-numeric lat/lon

---

### `GET /v1/catalog?dc_id=<id>&category=<cat>&q=<query>&page=1&page_size=30`

Browse or search products at a DC with real-time availability. Query params: `dc_id` (required), `category` (optional, exact match), `q` (optional, ILIKE substring search), `page` (default 1), `page_size` (default 30, max 100).

- **200**
  ```json
  {
    "items": [
      {
        "product_id": "550e8400-...",
        "name": "Lay's Classic Potato Chips",
        "brand": "Lay's",
        "category": "snacks",
        "unit_price_cents": 399,
        "available_qty": 12,
        "available": true
      }
    ],
    "page": 1,
    "page_size": 30,
    "total": 45
  }
  ```
  Products with `available_qty = 0` included with `available: false`. When `q` is provided, in-stock items appear first. Empty result returns `items: [], total: 0`.

- **400** `{"detail": "dc_id is required"}`
- **404** `{"detail": "DC not found"}`

---

### `POST /v1/orders`

Create a multi-item order with atomic inventory reservation. Client provides `order_id` for idempotency.

Request body:
```json
{
  "dc_id": "PHL-01",
  "items": [
    {"product_id": "550e8400-...", "quantity": 2}
  ],
  "delivery_address": "123 Market St, Philadelphia, PA 19106",
  "order_id": "660e8400-..."
}
```

- **201** — Order created, inventory reserved
  ```json
  {
    "order_id": "660e8400-...",
    "status": "confirmed",
    "items": [
      {
        "product_id": "550e8400-...",
        "name": "Lay's Classic Potato Chips",
        "quantity": 2,
        "unit_price_cents": 399
      }
    ],
    "total_amount_cents": 798,
    "delivery_address": "123 Market St, Philadelphia, PA 19106",
    "created_at": "2026-06-29T18:00:00Z",
    "updated_at": "2026-06-29T18:00:00Z"
  }
  ```

- **200** — Idempotent replay (same `order_id` submitted again). Returns the existing order state. No inventory change.

- **409** — Partial stock
  ```json
  {
    "status": "partial",
    "unavailable": [
      {"product_id": "550e8400-...", "quantity_available": 1}
    ]
  }
  ```

- **400** — missing dc_id, items, delivery_address, order_id, or invalid format
- **404** — unknown dc_id

---

### `GET /v1/orders/{order_id}`

Retrieve an order with line items and current status.

- **200** — same shape as create response above
- **404** `{"detail": "Order not found"}`

---

### `POST /v1/orders/{order_id}/status`

Advance order through status lifecycle.

Request body:
```json
{"status": "picking"}
```

- **200**
  ```json
  {
    "order_id": "...",
    "status": "picking",
    "updated_at": "2026-06-29T18:05:00Z"
  }
  ```

- **409** — invalid transition (skip, backward, already terminal)
- **404** — unknown order

Valid transitions:
```
confirmed → picking → packed → en_route → delivered
```
cancelled and delivered are terminal states.

---

### `POST /v1/orders/{order_id}/cancel`

Cancel an order that has not yet been packed. Releases all reserved inventory.

- **200**
  ```json
  {
    "order_id": "...",
    "status": "cancelled",
    "updated_at": "2026-06-29T18:10:00Z"
  }
  ```

- **409** — order is packed, already delivered, or already cancelled
- **404** — unknown order

---

### `POST /v1/admin/sweep-reservations`

Expire all orders that have been in `confirmed` status for > 15 minutes. Cancels them and releases reservations.

- **200**
  ```json
  {
    "orders_cancelled": 3,
    "message": "Cancelled 3 expired order(s)"
  }
  ```
  Returns `orders_cancelled: 0` if nothing expired.

No auth for MVP — admin endpoints are unauthenticated.

### Error response shape

All error responses follow FastAPI's default format:
```json
{"detail": "Human-readable error message"}
```
422 validation errors include `loc`, `msg`, `type` fields.

## 7. Key decisions

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Inventory consistency | Pessimistic `FOR UPDATE` | Optimistic version-column | No retry logic. At MVP scale (~5 orders/min/DC), lock duration is ~5ms — contention is irrelevant. |
| Lock ordering | `product_id` ASC | None (DB decides) | Deterministic ordering prevents deadlocks between concurrent checkouts at the same DC. |
| Search | PostgreSQL ILIKE | Elasticsearch | MVP has ~40 SKUs per DC. ILIKE with index on `(dc_id, name)` is sufficient. No ranking beyond availability. |
| Availability cache | Redis with 60s TTL | Direct SQL JOIN on every read | Single `GET` per product vs JOIN. Catalog reads benefit from sub-millisecond cache hits. |
| Idempotency | Client-generated UUID as PK | Separate idempotency table | One less table. UUIDv4 is collision-safe. Simple `SELECT` check before insert. |
| Status lifecycle | Enum in application code | DB CHECK constraint | Application-layer validation is more flexible; the lifecycle order may change. |
| Reservation TTL | Manual sweep endpoint | Background cron/scheduler | MVP simplicity. One POST endpoint. Full build adds a cron loop. |
| Seed data | Python script | SQL dump | Human-readable, repeatable, populates both DB. |

## 8. Module layout

```
sd-local-delivery-backend-mvp/
├── src/local_delivery/
│   ├── __init__.py
│   ├── main.py                 # create_app() factory + lifespan + /healthz
│   ├── config.py               # Settings(BaseSettings): DATABASE_URL, REDIS_URL, APP_PORT
│   ├── db.py                   # async engine, get_session dependency
│   ├── redis.py                # Redis client dependency
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── dc.py               # GET /v1/dc/lookup
│   │   ├── catalog.py          # GET /v1/catalog
│   │   ├── orders.py           # POST /v1/orders, GET/POST /v1/orders/{id}
│   │   └── admin.py            # POST /v1/admin/sweep-reservations
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dc_service.py       # Haversine nearest-DC finder
│   │   ├── catalog_service.py  # browse + search + availability merge
│   │   ├── order_service.py    # create, get, advance status, cancel
│   │   └── inventory_service.py # reserve, release, sweep
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py             # declarative Base
│   │   ├── dc.py
│   │   ├── product.py
│   │   ├── inventory.py
│   │   ├── order.py
│   │   └── order_line_item.py
│   └── schemas/
│       ├── __init__.py
│       ├── dc.py               # DCLookupResponse
│       ├── catalog.py          # CatalogItem, CatalogPage
│       ├── order.py            # CreateOrderRequest, OrderResponse, SweepResponse
│       └── common.py           # ErrorResponse, PaginationParams
├── alembic/
│   ├── env.py
│   └── versions/
├── scripts/
│   └── seed.py                 # Seed 2 DCs, 40 products each, 4 categories
├── tests/
│   ├── conftest.py             # Test fixtures: SQLite, FakeRedis, ASGI client
│   ├── unit/
│   │   ├── test_dc_service.py
│   │   ├── test_catalog_service.py
│   │   ├── test_order_service.py
│   │   └── test_inventory_service.py
│   └── functional/
│       ├── test_catalog.py
│       ├── test_orders.py
│       └── test_order_lifecycle.py
├── verify/
│   ├── acceptance/
│   │   ├── conftest.py         # Black-box client + assertion helpers
│   │   ├── test_fr1_dc_lookup.py
│   │   ├── test_fr2_category_browse.py
│   │   ├── test_fr3_text_search.py
│   │   ├── test_fr4_create_order.py
│   │   ├── test_fr5_get_order.py
│   │   ├── test_fr6_advance_status.py
│   │   ├── test_fr7_cancel_order.py
│   │   └── test_fr8_sweep.py
│   └── manifest.env
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── .env.example
├── README.md
├── DESIGN.md
├── DEPLOY.md
├── SPEC.md
└── .gitignore
```

## 9. Functional requirements → acceptance test map

Each functional requirement has a corresponding executable black-box test in `verify/acceptance/`. These tests speak HTTP to the running system only — they never import the app.

| FR | Test file | Key assertions |
|---|---|---|
| FR1 — DC lookup | `test_fr1_dc_lookup.py` | 200 with dc_id + distance on valid coords; 404 on uncovered; 422 on missing params |
| FR2 — Category browse | `test_fr2_category_browse.py` | 200 with paginated items + available_qty; 404 on unknown DC; 400 on missing dc_id |
| FR3 — Text search | `test_fr3_text_search.py` | 200 with matching items, in-stock first; 200 empty on no match; case-insensitive |
| FR4 — Create order | `test_fr4_create_order.py` | 201 with confirmed order; 200 idempotent; 409 partial stock; 400/404 validation; multi-item |
| FR5 — Get order | `test_fr5_get_order.py` | 200 with full order shape; 404 unknown |
| FR6 — Advance status | `test_fr6_advance_status.py` | 200 valid transition; 409 skip/backward/cancelled; 404 unknown; full lifecycle walk |
| FR7 — Cancel order | `test_fr7_cancel_order.py` | 200 cancel + reservation release; 409 on packed/already-cancelled; 404 unknown; picking-OK |
| FR8 — Sweep | `test_fr8_sweep.py` | 200 with orders_cancelled count; non-expired orders untouched; picking/delivered immune |

White-box tests in `tests/unit/` and `tests/functional/` validate the service logic and API contracts in-process using SQLite and a fake Redis.

## 10. Test results

### SPEC.md §6 scenarios → `tests/functional/` coverage

| SPEC §6 scenario | Functional test | Coverage |
|---|---|---|
| **Idempotency** — duplicate POST returns 200, no double reservation | `test_orders.py::test_order_idempotent` | ✓ |
| **Inventory consistency** — partial stock returns 409 with unavailable list | `test_orders.py::test_order_partial_stock` | ✓ |
| **Reservation release** — cancel → reserved_qty decremented | `test_order_lifecycle.py::test_cancel_order_success` | ✓ |
| **Reservation sweep** — expired orders cancelled | `tests/unit/test_inventory_service.py` | ✓ |
| **Status lifecycle** — valid transitions; skip rejected with 409 | `test_order_lifecycle.py::test_advance_status_single_step`, `test_advance_status_full_lifecycle`, `test_advance_status_skip_rejected` | ✓ |
| **Validation** — missing dc_id → 400; unknown dc_id → 404 | `test_catalog.py::test_category_browse_missing_dc_id`, `test_category_browse_unknown_dc`, `test_orders.py::test_order_missing_dc_id`, `test_order_unknown_dc` | ✓ |
| **Search ordering** — in-stock first in search results | `verify/acceptance/test_fr3_text_search.py::test_text_search_in_stock_first` | ✓ |
| **Pagination** — page 2 returns correct offset; empty page returns `{items:[],total:N}` | `test_catalog.py::test_pagination`, `test_catalog.py::test_text_search_no_match` | ✓ |

### Acceptance suite (`verify/acceptance/`)

Black-box tests that run against a live, seeded instance at `API_BASE_URL`. The suite covers all 8 functional requirements with real HTTP requests. All tests self-discover necessary product IDs via the catalog API — no hardcoded UUIDs.

### CI

[![CI](https://github.com/iliazlobin/sd-local-delivery-backend-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/iliazlobin/sd-local-delivery-backend-mvp/actions/workflows/ci.yml)

The CI workflow builds the Docker image, starts the full stack, runs migrations, seeds data, and executes all three test layers: `tests/unit/`, `tests/functional/`, and `verify/acceptance/` against the live container.

### Run

```bash
# Start the stack
docker compose up --build -d

# Health check
curl -s http://localhost:8010/healthz
# → {"status": "ok"}

# Seed test data
docker compose exec app python scripts/seed.py

# Run white-box tests
pytest tests/ -v

# Run black-box acceptance suite (against running container)
API_BASE_URL=http://localhost:8010 pytest verify/acceptance/ -v
```
