# Local Delivery MVP — Build Spec

## 1. Goal & scope

Build the **MVP** of a local-delivery platform: customers browse a convenience-store catalog at their nearest micro-fulfillment center (DC), search products, place orders with atomic inventory reservation, and track order status. The MVP targets the core ordering path (FR1–FR4) on a single-DC deployment — PostgreSQL for all data, Redis for availability caching, no message queue or search engine.

**In scope**
- DC geo-lookup (Haversine), category browse, and text search with real-time availability
- Multi-item order creation with pessimistic row-locking for inventory consistency
- Idempotent order submission
- Order status lifecycle: confirmed → picking → packed → en_route → delivered
- Cancel order (before packing)
- Reservation TTL sweep (15-minute expiry)

**Out of scope**
- Substitution recommendations (FR5), order history/re-order (FR6)
- Kafka / outbox pattern — synchronous service calls only
- Elasticsearch — PostgreSQL ILIKE for search
- OSRM drive-time routing — Haversine only
- SSE push — polling for order status
- Real payment integration — mock auth
- Multi-DC deployment — single DC for MVP

## 2. Functional requirements

- **FR1 — DC Lookup.** Find the nearest active DC for a lat/lon. `GET /v1/dc/lookup?lat=39.95&lon=-75.16` → `200 {"dc_id":"PHL-01",…}`; bad location → `404`; missing params → `422`.

- **FR2 — Category browse.** Browse products at a DC with availability. `GET /v1/catalog?dc_id=PHL-01&category=snacks&page=1` → `200 {items:[{product_id,name,brand,category,unit_price_cents,available_qty}],…}`; unknown DC → `404`; missing dc_id → `400`. Products with `available_qty=0` included with `available:false`.

- **FR3 — Text search.** Search products by name with availability. `GET /v1/catalog?dc_id=PHL-01&q=chips` → `200` with in-stock items first; empty result → `200 {items:[],total:0}`. Uses PostgreSQL `ILIKE`.

- **FR4 — Create order.** `POST /v1/orders {dc_id,items:[{product_id,qty}],delivery_address,order_id}` → `201 {order_id,status:"confirmed",…}`. Pessimistic row-locking (`SELECT…FOR UPDATE` in product_id order). Partial stock → `409 {status:"partial",unavailable:[…]}`. Duplicate `order_id` → `200` (idempotent). Missing fields → `400`; unknown DC → `404`.

- **FR5 — Get order.** `GET /v1/orders/{order_id}` → `200 {order_id,status,items,total_amount_cents,created_at,updated_at}`. Unknown → `404`.

- **FR6 — Advance status.** `POST /v1/orders/{order_id}/status {status}` → `200`. Must follow lifecycle order (confirmed→picking→packed→en_route→delivered). Skip → `409`. Unknown → `404`.

- **FR7 — Cancel order.** `POST /v1/orders/{order_id}/cancel` → `200` (allowed only in confirmed/picking). Releases reservations. Already cancelled/packed → `409`. Unknown → `404`.

- **FR8 — Reservation expiry.** A sweep cancels orders in `confirmed` status older than 15 minutes, releasing all reservations. Exposed as `POST /v1/admin/sweep-reservations` for the MVP.

## 3. Stack & deployment

- **Runtime:** Python 3.12 + FastAPI (async), uvicorn
- **Datastore:** PostgreSQL 16 (all data — no separate search engine), Alembic migrations
- **Cache:** Redis 7 (availability snapshots per DC)
- **Tests:** pytest + httpx (black-box `verify/acceptance/` + white-box `tests/unit/` + `tests/functional/`)
- **Deploy:** Docker Compose (`app` + `db` + `redis`), app on `${APP_PORT:-8010}:8000`
- **Design →** [System Design: Local Delivery](https://notion.so/38ed865005a881cdb6b0f23bf975a989) · board: `projects`

## 4. Data model

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
  dc_id: text (FK → DC)          ← composite unique with name
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
  order_id: uuid (PK)
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

## 5. API

- `GET /v1/dc/lookup?lat=<lat>&lon=<lon>` — nearest active DC within delivery radius (Haversine)
- `GET /v1/catalog?dc_id=<id>&category=<cat>&q=<query>&page=1&page_size=30` — browse/search products with availability
- `POST /v1/orders` — create order with atomic inventory reservation; idempotent on `order_id`
- `GET /v1/orders/{order_id}` — get order status and line items
- `POST /v1/orders/{order_id}/status` — advance order status through lifecycle
- `POST /v1/orders/{order_id}/cancel` — cancel order and release reservations
- `POST /v1/admin/sweep-reservations` — expire orders in `confirmed` > 15 min
- `GET /healthz` — health check

## 6. Test scenarios

- **Idempotency:** Duplicate `POST /v1/orders` with same `order_id` returns 200, no double reservation
- **Inventory consistency:** Two concurrent checkouts for last-in-stock item — one succeeds, one gets 409 partial
- **Reservation release:** Cancel order → reserved_qty decremented; sweep → expired orders cancelled
- **Status lifecycle:** Valid transitions (confirmed→picking→packed→en_route→delivered); skip rejected with 409
- **Validation:** Missing dc_id → 400; unknown dc_id → 404; missing required fields → 422
- **Search ordering:** In-stock items appear before out-of-stock in search results
- **Pagination:** Page 2 returns correct offset; empty page returns `{items:[],total:N}`

## 7. Module layout

```
sd-local-delivery-backend-mvp/
├── src/local_delivery/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory + lifespan
│   ├── config.py             # pydantic-settings
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── dc.py             # GET /v1/dc/lookup
│   │   ├── catalog.py        # GET /v1/catalog
│   │   ├── orders.py         # POST /v1/orders, GET/POST /v1/orders/{id}
│   │   └── admin.py          # POST /v1/admin/sweep-reservations
│   ├── services/
│   │   ├── __init__.py
│   │   ├── dc_service.py     # geo lookup (Haversine)
│   │   ├── catalog_service.py # product search + availability
│   │   ├── order_service.py  # order creation, status, cancel
│   │   └── inventory_service.py # reserve, release, sweep
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py           # SQLAlchemy Base
│   │   ├── dc.py
│   │   ├── product.py
│   │   ├── inventory.py
│   │   ├── order.py
│   │   └── order_line_item.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── dc.py
│   │   ├── catalog.py
│   │   ├── order.py
│   │   └── common.py         # pagination, error responses
│   └── db.py                 # session dependency
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── __init__.py
│   │   └── test_dc_service.py
│   └── functional/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_catalog.py
│       ├── test_orders.py
│       └── test_order_lifecycle.py
├── verify/
│   ├── __init__.py
│   ├── acceptance/
│   │   ├── __init__.py
│   │   ├── conftest.py
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
├── README.md
├── DESIGN.md
├── DEPLOY.md
├── SPEC.md
└── .gitignore
```

## 8. Run

```bash
# Start the stack
docker compose up -d

# Health check
curl http://localhost:8010/healthz
# → {"status": "ok"}

# Seed test data (optional)
python3 scripts/seed.py

# Run tests
pytest tests/unit/ tests/functional/ -v

# Run acceptance suite (against running container)
API_BASE_URL=http://localhost:8010 pytest verify/acceptance/ -v
```
