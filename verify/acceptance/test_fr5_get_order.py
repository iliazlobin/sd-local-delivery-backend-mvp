"""FR5 — Get order by ID.

AC5: GET /v1/orders/{order_id} -> 200 with full order shape.
     Unknown order_id -> 404.
"""

import uuid

from verify.acceptance.conftest import assert_200, assert_201, assert_404


def _create_test_order(client):
    """Helper: create an order and return the response body (status 201)."""
    # Discover a product first
    catalog = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "page": 1, "page_size": 10},
        )
    )
    available = [i for i in catalog["items"] if i.get("available") and i["available_qty"] > 0]
    if not available:
        raise RuntimeError("No available products for order creation")
    product = available[0]

    return assert_201(
        client.post(
            "/v1/orders",
            json={
                "dc_id": "PHL-01",
                "items": [{"product_id": product["product_id"], "quantity": 1}],
                "delivery_address": "123 Market St, Philadelphia, PA 19106",
                "order_id": str(uuid.uuid4()),
            },
        )
    )


def test_get_order_success(client):
    """Retrieving an existing order returns 200 with full shape."""
    created = _create_test_order(client)

    body = assert_200(client.get(f"/v1/orders/{created['order_id']}"))

    assert body["order_id"] == created["order_id"]
    assert body["status"] == "confirmed"
    assert "items" in body
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 1
    assert "total_amount_cents" in body
    assert body["total_amount_cents"] > 0
    assert "delivery_address" in body
    assert "created_at" in body
    assert "updated_at" in body

    # Each line item must have expected fields
    for item in body["items"]:
        assert "product_id" in item
        assert "name" in item
        assert "quantity" in item
        assert "unit_price_cents" in item


def test_get_order_not_found(client):
    """An unknown order_id returns 404."""
    fake_id = str(uuid.uuid4())
    assert_404(client.get(f"/v1/orders/{fake_id}"))


def test_get_order_after_status_change(client):
    """After advancing status, GET returns the updated status."""
    created = _create_test_order(client)

    # Advance to picking
    assert_200(
        client.post(
            f"/v1/orders/{created['order_id']}/status",
            json={"status": "picking"},
        )
    )

    body = assert_200(client.get(f"/v1/orders/{created['order_id']}"))
    assert body["status"] == "picking"
    assert body["updated_at"] != body["created_at"]  # Should have been updated
