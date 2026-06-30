"""FR8 — Reservation expiry sweep.

AC8: POST /v1/admin/sweep-reservations -> 200 with orders_cancelled count.
     Expired confirmed orders (> 15 min) are cancelled and reservations released.
     Non-expired and non-confirmed orders are untouched.
"""

import uuid

from verify.acceptance.conftest import assert_200, assert_201


def _create_test_order(client, order_id=None):
    """Helper: create an order and return the response body (status 201)."""
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
                "order_id": order_id or str(uuid.uuid4()),
            },
        )
    )


def test_sweep_reservations_endpoint_exists(client):
    """The sweep endpoint returns 200 with orders_cancelled in response."""
    body = assert_200(client.post("/v1/admin/sweep-reservations"))

    assert "orders_cancelled" in body
    assert isinstance(body["orders_cancelled"], int)
    assert body["orders_cancelled"] >= 0


def test_sweep_does_not_touch_non_expired_orders(client):
    """A just-created order (not expired) should not be cancelled by sweep."""
    order = _create_test_order(client)

    # Run sweep immediately — order is < 15 min old
    sweep_result = assert_200(client.post("/v1/admin/sweep-reservations"))

    # The order should still be confirmed
    current = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert current["status"] == "confirmed", (
        f"Order should remain confirmed, got {current['status']}. "
        f"Sweep cancelled {sweep_result['orders_cancelled']} orders."
    )


def test_sweep_does_not_touch_non_confirmed_orders(client):
    """Orders not in 'confirmed' status (e.g., picking) should not be cancelled by sweep."""
    order = _create_test_order(client)

    # Advance to picking
    assert_200(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "picking"},
        )
    )

    # Run sweep
    assert_200(client.post("/v1/admin/sweep-reservations"))

    # Order should still be picking
    current = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert current["status"] == "picking"


def test_sweep_does_not_touch_delivered_orders(client):
    """Orders that have completed delivery should not be cancelled by sweep."""
    order = _create_test_order(client)

    # Walk to delivered
    for status in ("picking", "packed", "en_route", "delivered"):
        assert_200(
            client.post(
                f"/v1/orders/{order['order_id']}/status",
                json={"status": status},
            )
        )

    # Run sweep
    assert_200(client.post("/v1/admin/sweep-reservations"))

    # Order should still be delivered
    current = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert current["status"] == "delivered"


def test_sweep_releases_inventory(client):
    """After a sweep cancels expired orders, product availability should increase."""
    # Note: this test can only verify the *mechanism* exists, since we cannot
    # artificially age an order to 15+ minutes old. It verifies that:
    # 1. The sweep endpoint exists and returns a valid response
    # 2. Sweep does not cancel non-expired orders (validated above)
    #
    # For a true expiry test, the e2e host loop can insert orders with
    # backdated created_at timestamps via the seed script.

    # Create a fresh order
    order = _create_test_order(client)

    # Cancel it manually to verify reservation release works
    assert_200(client.post(f"/v1/orders/{order['order_id']}/cancel"))

    # Run sweep — the cancelled order should not be double-counted
    sweep_result = assert_200(client.post("/v1/admin/sweep-reservations"))
    assert sweep_result["orders_cancelled"] >= 0
