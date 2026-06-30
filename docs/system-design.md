# System Design: Local Delivery

A local-delivery platform that lets customers order convenience-store goods from nearby micro-fulfillment centers, delivered in 30 minutes. The operator runs ~500 dark stores across US metros, each stocking 2,000–4,000 SKUs within a 2–3 mile delivery radius.

## 1. Problem frame

A user opens the app, sees products available at their nearest dark store, searches for "sparkling water," adds items to cart, and checks out. The system must reserve inventory atomically so two customers can't buy the last can simultaneously. Once confirmed, the order flows through picking → packing → delivery while the customer tracks status in real time.

## 2. Requirements

**Functional**

- **FR1:** Browse a product catalog filtered to the DC serving the user's delivery address
- **FR2:** Search products by name, category, or brand with real-time stock availability
- **FR3:** Place a multi-item order for delivery within a 30-minute window
- **FR4:** Track an order from placement through picking, packing, and delivery in real time
- **FR5:** Receive substitution recommendations when a picked item is out of stock
- **FR6:** View order history and re-order from a past purchase in one tap

**Non-functional**

- **NFR1:** Catalog reads with availability filtering return p95 under 200 ms
- **NFR2:** 99.95% availability during peak evening hours (6pm–10pm local time)
- **NFR3:** No customer is sold an item already allocated to another active checkout
- **NFR4:** Order status events visible to the customer within 5 seconds of occurrence

**Out of scope:** fleet routing and ETA optimization, driver onboarding and payouts, DC restocking and supply-chain forecasting, promotional pricing engines, subscription/membership tiers.

## 3. Back of the envelope

- 500 DCs × ~3,000 SKUs/DC → 1.5M inventory rows total, ~10 GB without indexes
- 500 DCs × 5 orders/min peak rush → ~42 orders/s sustained
- 2M DAU × 3 page loads/session → ~6M catalog reads/day ≈ 70 QPS average, 200 QPS peak
- Each order touches inventory (reserve + deduct), payment (authorize + capture), and fulfillment (dispatch picker)
- The concurrency point is the per-DC inventory row — at 5 orders/min per DC, the contention window is ~12 seconds per order

## 4. Entities & API

**Entities:**

```
DC
  dc_id: string (PK)              ← short code, e.g. "PHL-12"
  geo_hash: string (INDEX)        ← GeoHash-7 (~153m × 153m cell); spatial index key
  center_lat: double              ← actual lat/lon
  center_lon: double
  delivery_radius_mi: double
  status: string                  ← active | inactive
  name: string

Product
  product_id: uuid (PK)
  name: string
  brand: string
  category: string
  is_active: boolean
  unit_price_cents: int

Inventory
  inventory_id: uuid (PK)
  dc_id: string (FK → DC)         ← composite unique with product_id
  product_id: uuid (FK → Product)
  stock_on_hand: int              ← physical count at DC
  reserved_qty: int               ← held for active checkouts (TTL 15 min)
  version: int                    ← optimistic-concurrency column
  UNIQUE (dc_id, product_id)

Order
  order_id: uuid (PK)
  user_id: uuid
  dc_id: string (FK → DC)
  status: string                  ← cart | confirmed | picking | packed | en_route | delivered | cancelled
  total_amount_cents: int
  delivery_address: jsonb
  created_at: timestamp
  updated_at: timestamp

OrderLineItem
  line_item_id: uuid (PK)
  order_id: uuid (FK → Order)
  product_id: uuid (FK → Product)
  quantity: int
  actual_product_id: uuid?        ← nullable; set if substituted
  substitution_reason: string?
  unit_price_cents: int
```

**API:**

- `GET /v1/dc/lookup?lat=39.95&lon=-75.16` — find the DC serving an address; returns `dc_id`
- `GET /v1/catalog?dc_id=PHL-12&category=snacks&q=chips&page=1` — browse/search products with real-time availability at a DC
- `POST /v1/orders` — create an order; body: `{dc_id, items[{product_id, quantity}], delivery_address, payment_method_id}`; returns `order_id`
- `GET /v1/orders/{order_id}` — current order status + line items + substitutions
- `POST /v1/orders/{order_id}/cancel` — cancel before picking starts; releases reservations
- `POST /v1/orders/reorder/{previous_order_id}` — re-create a cart from a past order

## 5. High-Level Design

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway                               │
│              auth, geo-locate, rate-limit                        │
└──────┬──────────┬──────────┬──────────┬──────────────────────────┘
       │          │          │          │
   Catalog    Order     Inventory   Fulfillment
   Service    Service    Service     Service
       │          │          │          │
   ┌───┴───┐  ┌───┴───┐  ┌───┴───┐  ┌───┴───┐
   │PostgreSQL│PostgreSQL│PostgreSQL│  Kafka  │
   │+ Redis  │         │         │  (events)│
   └───────┘  └───────┘  └───────┘  └───────┘
```

### FR1: Browse catalog filtered to DC

1. Client calls `GET /v1/dc/lookup?lat=...&lon=...` on app open or address change
2. Geo Index runs a spatial query: nearest DC with `status=active` within `delivery_radius_mi`. Uses GeoHash prefix scan (7-char ≈ 150m cell) followed by Haversine filter
3. Gateway caches `user_id → dc_id` mapping in a session cookie (TTL 1 hour)
4. Catalog Service receives `GET /v1/catalog?dc_id=PHL-12&category=snacks&page=1`
5. Queries Product table for matching SKUs, bulk-fetches availability from Redis: `HMGET dc:PHL-12:stock product:4821 product:1733 ...`
6. Products with `available_qty = 0` shown as "out of stock"; results paginated (30 items/page)

### FR2: Search products with availability

1. Client sends `GET /v1/catalog?dc_id=PHL-12&q=sparkling water`
2. Catalog Service routes text queries to Elasticsearch (full-text index). Query: multi_match against name, brand, category with boosting
3. Elasticsearch returns `product_id` + relevance score
4. Catalog Service pipeline-fetches availability from Redis for all matching product IDs
5. Service merges availability into response; in-stock items first within each relevance tier

### FR3: Place a multi-item order

1. Client sends `POST /v1/orders` with `{dc_id, items, delivery_address, payment_method_id}`
2. Order Service checks idempotency on `order_id` (UUIDv4, client-generated)
3. Order Service calls Inventory Service: `POST /v1/inventory/reserve`
4. Inventory Service runs a transactional reserve with pessimistic row-locking (`SELECT ... FOR UPDATE`), locking rows in product_id ASC order to prevent deadlocks
5. On full reservation success, Order Service calls Payment Service for pre-auth
6. Order Service inserts Order + OrderLineItem rows and returns `{order_id, status: "confirmed"}`

**Reservation TTL:** 15-minute hold. A sweep job releases expired reservations.

### FR4: Track order in real time

1. After confirmation, Fulfillment Service consumes OrderCreated from Kafka and dispatches picker
2. As picker scans items, status advances: picking → packed → en_route → delivered
3. SSE push worker consumes Kafka topic, filters by `order_id`, pushes events via `GET /v1/events/{order_id}` SSE stream

### FR5: Substitution recommendations

1. When picker finds item out of stock, picking app shows "Item Unavailable"
2. Fulfillment Service queries Catalog Service for top-3 candidates: same category, active, in-stock at DC, ranked by `substitution_success_rate`
3. Picker selects or skips; choice written to OrderLineItem

### FR6: Order history and re-order

1. `GET /v1/orders?user_id=<id>&page=1&limit=20` queries user-scoped order history
2. `POST /v1/orders/reorder/{previous_order_id}` clones items from past order into a new cart
3. Re-order validates current availability — OOS items returned with `available: false`

## 6. Deep dives

### DD1: Inventory consistency — pessimistic row-locking

**Decision:** Pessimistic row-level locking on checkout, with deterministic lock ordering by `product_id` within each DC-scoped partition.

On checkout, Inventory Service locks all line-item rows:
```sql
BEGIN;
SELECT product_id, stock_on_hand, reserved_qty
FROM inventory
WHERE dc_id = :dc_id AND product_id = ANY(:product_ids)
ORDER BY product_id    -- deterministic order prevents deadlocks
FOR UPDATE;
```

Rows are locked in product_id ASC order, eliminating deadlocks. Lock held only for the reserve transaction (~5–10ms). The reservation carries a 15-minute TTL (FR3).

**Why not optimistic concurrency?** Under low contention (~5 orders/min/DC), retries rarely exceed 1. But under flash-sale contention, retry storms degrade non-deterministically — no fairness guarantee.

**Why not Redis Redlock?** Inventory locks must be transactional with the reservation write. Redlock can't participate in a PostgreSQL transaction — a crashed service between lock-acquire and DB-write leaves a dangling lock.

### DD2: Geo-spatial DC discovery — GeoHash + Haversine

**Decision:** GeoHash prefix scan + Haversine for DC assignment at browse time; OSRM drive-time verification at checkout for addresses near DC boundaries.

Every DC indexed by GeoHash-7 prefix (~153m × 153m cell). DC lookup queries all DCs sharing the user's prefix + 8 adjacent cells (typically 1–3 DCs), ranks by Haversine distance. At checkout, OSRM verifies drive time for addresses within 0.5 mi of a DC boundary (~5% of checkouts).

**Fallback:** If OSRM is unavailable, fall back to Haversine ranking — 5–8% boundary-error rate is temporarily exposed.

### DD3: Availability caching — Redis per-DC snapshot

**Decision:** Redis per-DC inventory snapshot with 30-second TTL for browse-level availability; transactional DB check at cart-add for correctness.

An InventorySnapshotter worker bulk-loads current inventory into Redis every 30 seconds per DC partition. Catalog reads use `HMGET dc:PHL-12:stock product:4821 product:1733 ...` — single Redis call, sub-millisecond. At cart-add, a real-time check against the transactional DB confirms availability.

### DD4: Order lifecycle — event-driven choreography with outbox

**Decision:** Event-driven choreography with outbox pattern, idempotency keyed on `order_id + event_type`, with a reconciliation job for dangling gateway states.

Order Service is the orchestrator. Each step publishes domain events to Kafka via the outbox pattern. Downstream services react idempotently. A reconciliation job (every 5 minutes) resolves stuck orders by querying the payment gateway for dangling auths.

## 7. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Inventory locking | Pessimistic row-lock | Optimistic version-column | No retry storms; fairness under contention; standard at Amazon/Uber scale |
| DC discovery | GeoHash + Haversine | GeoJSON polygons | No polygon maintenance; naturally handles overlapping DCs |
| Availability reads | Redis snapshot (30s TTL) | Read replicas | Sub-millisecond; no replication-lag ghost stock at browse time |
| Order lifecycle | Choreography + outbox | Synchronous orchestration | No dual-write problem; each service independently scalable |
| Search | Elasticsearch (secondary index) | PostgreSQL full-text | Relevance ranking; category boosting; CDC'd via Kafka Connect |

## 8. References

- Uber: Evolution and Scale of Delivery Search Platform — two-tower semantic search, HNSW indexing
- Uber: Cart Assistant — Agentic Grocery Shopping on Uber Eats
- PostgreSQL: SELECT FOR UPDATE and Row-Level Locks
- Redis: Pipelining and Hashes for Bulk Reads — HMGET for batch field retrieval
- Kafka: Exactly-Once Semantics and the Outbox Pattern
- OSRM: Open Source Routing Machine — Table Service
- DoorDash: Building a Scalable Search and Discovery Platform
- Instacart: Real-Time Inventory and Fulfillment Architecture
- GoPuff Engineering Blog — micro-fulfillment center operations
