"""FR4 — Create order with atomic inventory reservation.

AC4: POST /v1/orders with valid items -> 201 with confirmed order.
     Idempotency: same order_id -> 200, no double reservation.
     Partial stock -> 409 with unavailable list.
     Missing fields -> 400.
     Unknown DC -> 404.
"""

import uuid

from verify.acceptance.conftest import assert_200, assert_201, assert_400, assert_404, assert_409


def _get_first_available_product(client, dc_id="PHL-01"):
    """Discover a product with available stock by browsing the catalog."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": dc_id, "page": 1, "page_size": 10},
        )
    )
    for item in body["items"]:
        if item.get("available") and item["available_qty"] > 0:
            return item
    raise RuntimeError("No available products found — seed data may be missing")


def _get_second_product_in_stock(client, dc_id="PHL-01"):
    """Discover a second in-stock product distinct from the first."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": dc_id, "page": 1, "page_size": 30},
        )
    )
    in_stock = [i for i in body["items"] if i.get("available") and i["available_qty"] > 0]
    if len(in_stock) < 2:
        raise RuntimeError("Need at least 2 in-stock products for multi-item test")
    return in_stock[1]


def test_create_order_success(client):
    """Valid order with in-stock items returns 201 and confirms the order."""
    product = _get_first_available_product(client)
    order_id = str(uuid.uuid4())

    body = assert_201(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [{"product_id": product["product_id"], "quantity": 1}],
                "delivery_address": "123 Market St, Philadelphia, PA 19106",
                "order_id": order_id,
            },
        )
    )

    assert body["order_id"] == order_id
    assert body["status"] == "confirmed"
    assert "items" in body
    assert len(body["items"]) == 1
    assert body["items"][0]["product_id"] == product["product_id"]
    assert body["items"][0]["quantity"] == 1
    assert "unit_price_cents" in body["items"][0]
    assert "total_amount_cents" in body
    assert isinstance(body["total_amount_cents"], int)
    assert body["total_amount_cents"] > 0
    assert body["delivery_address"] == "123 Market St, Philadelphia, PA 19106"
    assert "created_at" in body
    assert "updated_at" in body


def test_order_idempotent(client):
    """Submitting the same order_id twice returns 200 on the second call, no double reservation."""
    product = _get_first_available_product(client)
    order_id = str(uuid.uuid4())

    # First call — creates the order
    r1 = assert_201(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [{"product_id": product["product_id"], "quantity": 1}],
                "delivery_address": "456 Elm St, Philadelphia, PA 19106",
                "order_id": order_id,
            },
        )
    )

    # Second call with same order_id — idempotent, returns 200 (not 201)
    r2 = assert_200(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [{"product_id": product["product_id"], "quantity": 1}],
                "delivery_address": "456 Elm St, Philadelphia, PA 19106",
                "order_id": order_id,
            },
        )
    )

    # Both responses should match in structure
    assert r2["order_id"] == r1["order_id"]
    assert r2["status"] == r1["status"]
    assert r2["total_amount_cents"] == r1["total_amount_cents"]


def test_order_partial_stock(client):
    """Requesting more than available stock returns 409 with unavailable list."""
    product = _get_first_available_product(client)

    # Request 9999 units — should exceed stock_on_hand
    body = assert_409(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [{"product_id": product["product_id"], "quantity": 9999}],
                "delivery_address": "789 Pine St, Philadelphia, PA 19106",
                "order_id": str(uuid.uuid4()),
            },
        )
    )

    assert body["status"] == "partial"
    assert "unavailable" in body
    assert isinstance(body["unavailable"], list)
    assert len(body["unavailable"]) > 0
    assert body["unavailable"][0]["product_id"] == product["product_id"]
    assert "quantity_available" in body["unavailable"][0]


def test_order_missing_required_fields(client):
    """Missing dc_id returns 400."""
    product = _get_first_available_product(client)

    assert_400(
        client.post(
            "/v1/orders",
            json={
                "items": [{"product_id": product["product_id"], "quantity": 1}],
                "delivery_address": "123 Main St",
                "order_id": str(uuid.uuid4()),
            },
        )
    )

    # Missing items
    assert_400(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "delivery_address": "123 Main St",
                "order_id": str(uuid.uuid4()),
            },
        )
    )


def test_order_unknown_dc(client):
    """An unknown dc_id returns 404."""
    product = _get_first_available_product(client)

    assert_404(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "NONEXISTENT",
                "items": [{"product_id": product["product_id"], "quantity": 1}],
                "delivery_address": "123 Main St",
                "order_id": str(uuid.uuid4()),
            },
        )
    )


def test_order_unknown_product(client):
    """Ordering a product that does not exist at the DC should fail gracefully."""
    fake_product_id = str(uuid.uuid4())
    body = client.post(
        "/v1/orders",
        json={
            "dc_id": "PHL-01",
            "items": [{"product_id": fake_product_id, "quantity": 1}],
            "delivery_address": "123 Main St",
            "order_id": str(uuid.uuid4()),
        },
    )
    # Should be an error — either 400, 404, or 409 depending on implementation approach
    assert body.status_code in (
        400,
        404,
        409,
    ), f"Expected 400/404/409 for unknown product, got {body.status_code}: {body.text}"


def test_order_multi_item(client):
    """Order with multiple line items succeeds and returns all items."""
    p1 = _get_first_available_product(client)
    p2 = _get_second_product_in_stock(client)

    body = assert_201(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [
                    {"product_id": p1["product_id"], "quantity": 1},
                    {"product_id": p2["product_id"], "quantity": 1},
                ],
                "delivery_address": "10 Broad St, Philadelphia, PA 19106",
                "order_id": str(uuid.uuid4()),
            },
        )
    )

    assert len(body["items"]) == 2
    returned_ids = {i["product_id"] for i in body["items"]}
    assert p1["product_id"] in returned_ids
    assert p2["product_id"] in returned_ids
    # Total should be sum of unit prices
    expected_total = p1["unit_price_cents"] + p2["unit_price_cents"]
    assert body["total_amount_cents"] == expected_total


def test_order_partial_stock_multi_item(client):
    """Multi-item order where one item has insufficient stock returns 409 with unavailable list."""
    p1 = _get_first_available_product(client)
    p2 = _get_second_product_in_stock(client)

    body = assert_409(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [
                    {"product_id": p1["product_id"], "quantity": 1},
                    {"product_id": p2["product_id"], "quantity": 99999},
                ],
                "delivery_address": "10 Broad St, Philadelphia, PA 19106",
                "order_id": str(uuid.uuid4()),
            },
        )
    )

    assert body["status"] == "partial"
    assert "unavailable" in body
    assert len(body["unavailable"]) >= 1
    # The unavailable item should be p2
    unavailable_ids = {u["product_id"] for u in body["unavailable"]}
    assert p2["product_id"] in unavailable_ids
