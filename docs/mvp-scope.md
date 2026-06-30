# Local Delivery MVP — Scope & Acceptance Criteria

## Stack

- **Runtime:** Python 3.12 + FastAPI (async)
- **Datastore:** PostgreSQL (all data; no Kafka, no Elasticsearch for MVP)
- **Cache:** Redis (availability snapshots per DC)
- **Tests:** pytest (black-box acceptance + white-box unit/functional)
- **Deploy:** Docker Compose (app + db + redis), no host port for internal services

## Scope IN (this build)

- FR1: Browse catalog filtered to DC (DC lookup + category browse with availability)
- FR2: Search products by name with real-time stock availability (PostgreSQL ILIKE, not Elasticsearch)
- FR3: Place a multi-item order with atomic inventory reservation (pessimistic row-locking)
- FR4: Order status tracking (polling GET, not SSE push)

## Scope OUT (deferred to full build)

- FR5: Substitution recommendations (requires picking-app flow)
- FR6: Order history and re-order
- Kafka / outbox pattern — MVP uses direct synchronous service calls
- Elasticsearch — MVP uses PostgreSQL `ILIKE` for search
- OSRM drive-time verification — MVP uses Haversine only
- SSE push for order tracking — MVP uses polling
- Payment integration — MVP simulates payment (accepts `payment_method_id`, returns mock `auth_code`)
- Real-time inventory snapshotter — MVP uses a simple manual refresh or on-demand Redis load

## Functional Requirements (MVP cut)

### FR1 — Browse catalog filtered to DC

Browse products at a DC, filtered by category, with real-time stock availability.

- **FR1.1 — DC Lookup:** `GET /v1/dc/lookup?lat=<lat>&lon=<lon>` returns the `dc_id` of the nearest active DC
  within delivery radius (Haversine-based). Returns `404` if no DC covers the location.

- **FR1.2 — Category browse:** `GET /v1/catalog?dc_id=<id>&category=<cat>&page=1&page_size=30`
  returns paginated products in that category with `available_qty` (stock_on_hand - reserved_qty).
  Products with zero availability are included but marked `available: false`.
  Returns `404` for unknown DC, `400` for missing `dc_id`.

### FR2 — Search products by name

Full-text-ish search over product name within a DC.

- **FR2.1 — Text search:** `GET /v1/catalog?dc_id=<id>&q=<query>&page=1&page_size=30`
  returns products whose `name` contains the query (case-insensitive `ILIKE '%query%'`), with availability.
  Results ranked: in-stock first, then out-of-stock. Paginated. Empty query returns all products.

### FR3 — Place a multi-item order with inventory reservation

Atomic reservation of inventory for a checkout.

- **FR3.1 — Create order:** `POST /v1/orders` with body `{dc_id, items: [{product_id, quantity}], delivery_address}`
  - Validates all `product_id`s exist at the DC
  - Acquires pessimistic row locks (`SELECT ... FOR UPDATE`) in product_id order
  - Checks `stock_on_hand - reserved_qty >= quantity` for every item
  - If any item has insufficient stock → returns `409` with `{status: "partial", unavailable: [{product_id, quantity_available}]}`
  - If all items available → reserves them (increments `reserved_qty`), creates Order (status=`confirmed`), returns `201` with `{order_id, status: "confirmed", items: [...], total_amount_cents, created_at}`
  - **Idempotency:** Client provides `order_id` (UUIDv4) in request body. Duplicate submission with same `order_id` returns `200` with the existing order state (no re-processing).
  - Returns `400` for missing required fields, `404` for unknown `dc_id`

- **FR3.2 — Reservation expiry:** A reservation TTL sweep (simple: order in `cart` status > 15 minutes is cancelled, releasing reservations)

### FR4 — Track order status

Poll-based order status.

- **FR4.1 — Get order:** `GET /v1/orders/{order_id}` returns the current order with status, line items, and timestamps.
  - Status lifecycle: `confirmed` → `picking` → `packed` → `en_route` → `delivered`
  - Returns `404` for unknown order_id

- **FR4.2 — Advance status:** `POST /v1/orders/{order_id}/status` with body `{status: "picking"|"packed"|"en_route"|"delivered"}`
  - Validates the status transition (must follow the lifecycle order; can't skip states)
  - Returns `200` with updated order; `409` for invalid transition; `404` for unknown order

- **FR4.3 — Cancel order:** `POST /v1/orders/{order_id}/cancel`
  - Only allowed when `status IN (confirmed, picking)` — before packing starts
  - Releases all reservations for that order
  - Returns `200` with updated order (`status: "cancelled"`); `409` if order is past picking stage

## Acceptance Criteria (one per FR → one executable test per)

### AC1 — DC Lookup (FR1.1)
```
GET /v1/dc/lookup?lat=39.95&lon=-75.16 → 200 {dc_id: "PHL-01", name: "...", center_lat: ..., center_lon: ..., distance_mi: ...}
GET /v1/dc/lookup?lat=0&lon=0 → 404 (no DC covers that location)
GET /v1/dc/lookup (no params) → 422
```

### AC2 — Category Browse (FR1.2)
```
GET /v1/catalog?dc_id=PHL-01&category=snacks&page=1&page_size=30 → 200 {items: [{product_id, name, brand, category, unit_price_cents, available_qty}], page, page_size, total}
GET /v1/catalog?dc_id=NONEXISTENT&category=snacks → 404
GET /v1/catalog?category=snacks → 400 (missing dc_id)
```

### AC3 — Text Search (FR2.1)
```
GET /v1/catalog?dc_id=PHL-01&q=chips → 200 {items: [...]}  -- in-stock products first, then OOS
GET /v1/catalog?dc_id=PHL-01&q=xyznonexistent → 200 {items: [], total: 0}
```

### AC4 — Create Order (FR3.1)
```
POST /v1/orders {dc_id, items: [{product_id: <valid>, quantity: 2}], delivery_address: "123 Main St", order_id: <uuid>}
  → 201 {order_id, status: "confirmed", items: [...], total_amount_cents: ..., created_at: ...}

POST /v1/orders {same order_id, ...} → 200 {order_id, status: "confirmed", ...} (idempotent)

POST /v1/orders {dc_id, items: [{product_id: <valid>, quantity: 9999}]} → 409 {status: "partial", unavailable: [{product_id, quantity_available: N}]}

POST /v1/orders {items: [...]} (missing dc_id) → 400
POST /v1/orders {dc_id: "NONEXISTENT", items: [...]} → 404
```

### AC5 — Order Tracking (FR4.1)
```
GET /v1/orders/{order_id} → 200 {order_id, status, items: [...], total_amount_cents, created_at, updated_at}
GET /v1/orders/{nonexistent_id} → 404
```

### AC6 — Advance Status (FR4.2)
```
POST /v1/orders/{order_id}/status {status: "picking"} → 200
POST /v1/orders/{order_id}/status {status: "delivered"} → 409 (can't skip packed)
GET /v1/orders/{order_id} → status now "picking"
```

### AC7 — Cancel Order (FR4.3)
```
POST /v1/orders/{order_id}/cancel → 200 (if status is confirmed/picking)
GET /v1/orders/{order_id} → status: "cancelled"
Verify inventory: reserved_qty decremented by order quantity
POST /v1/orders/{order_id}/cancel → 409 (already cancelled)
```

## Build Plan

See `KICKOFF.md` for the kanban chain. Cards in order:

1. **architect** — Produce `design.md` with concrete module layout, data model decisions, and the executable `verify/acceptance/` suite (one case per FR above). No app code.
2. **senior-engineer** — Scaffold: `pyproject.toml`, `src/` layout, config, Alembic migrations, `GET /healthz`, Dockerfile skeleton, get the app to START.
3. **staff-engineer** — Implement all FRs until every `verify/acceptance/` case passes. Write `tests/unit/` + `tests/functional/`. Run `ruff` clean.
4. **verifier** — GATE: run all test layers, verify acceptance cases pass with pasted evidence. PASS or BLOCK.
5. **sre** — `docker-compose.yml`, `DEPLOY.md`, `.env.example`, `verify/manifest.env`, CI/CD workflows.
6. **writer** — `README.md` + `DESIGN.md`; fold `docs/mvp-scope.md`; delete build harness.
