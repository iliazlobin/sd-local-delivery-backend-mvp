"""FR7 — Cancel order and release reservations.

AC7: POST /v1/orders/{order_id}/cancel -> 200 (if status is confirmed or picking).
     Order status becomes "cancelled".
     Inventory reserved_qty is decremented by the order quantity.
     Already cancelled -> 409.
     Already packed -> 409.
     Unknown order -> 404.
"""

import uuid

from verify.acceptance.conftest import assert_200, assert_201, assert_404, assert_409


def _create_test_order(client):
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
                "order_id": str(uuid.uuid4()),
            },
        )
    )


def test_cancel_order_success(client):
    """Cancelling a confirmed order returns 200 and sets status to cancelled."""
    order = _create_test_order(client)

    body = assert_200(client.post(f"/v1/orders/{order['order_id']}/cancel"))
    assert body["status"] == "cancelled"

    # Verify via GET
    current = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert current["status"] == "cancelled"


def test_cancel_order_releases_reservation(client):
    """After cancellation, the product's available_qty should increase."""
    # First, check current availability of a product
    catalog = assert_200(
        client.get("/v1/catalog", params={"dc_id": "PHL-01", "page": 1, "page_size": 30})
    )
    available = [i for i in catalog["items"] if i.get("available") and i["available_qty"] > 0]
    if not available:
        raise RuntimeError("No available products")
    product = available[0]
    qty_before = product["available_qty"]

    # Create order (reserves 1)
    order = assert_201(
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

    # Cancel it
    assert_200(client.post(f"/v1/orders/{order['order_id']}/cancel"))

    # Check availability again — should have gone back up (released reservation)
    catalog2 = assert_200(
        client.get("/v1/catalog", params={"dc_id": "PHL-01", "page": 1, "page_size": 30})
    )
    for item in catalog2["items"]:
        if item["product_id"] == product["product_id"]:
            qty_after = item["available_qty"]
            # After cancelling, the available_qty should return to qty_before
            # (the 1 reserved unit was released)
            assert (
                qty_after == qty_before
            ), f"Available qty should be {qty_before} after cancel, got {qty_after}"
            break
    else:
        raise AssertionError("Product not found in catalog after cancellation")


def test_cancel_order_already_cancelled(client):
    """Cancelling an already cancelled order returns 409."""
    order = _create_test_order(client)

    assert_200(client.post(f"/v1/orders/{order['order_id']}/cancel"))
    # Second cancel should be 409
    assert_409(client.post(f"/v1/orders/{order['order_id']}/cancel"))


def test_cancel_order_packed_rejected(client):
    """Cannot cancel an order that is already packed."""
    order = _create_test_order(client)

    # Advance to packed
    assert_200(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "picking"},
        )
    )
    assert_200(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "packed"},
        )
    )

    # Try to cancel — should fail
    assert_409(client.post(f"/v1/orders/{order['order_id']}/cancel"))

    # Order status should remain packed
    current = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert current["status"] == "packed"


def test_cancel_order_unknown(client):
    """Cancelling an unknown order returns 404."""
    fake_id = str(uuid.uuid4())
    assert_404(client.post(f"/v1/orders/{fake_id}/cancel"))


def test_cancel_order_while_picking(client):
    """Cancelling an order in 'picking' status is allowed."""
    order = _create_test_order(client)

    # Advance to picking
    assert_200(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "picking"},
        )
    )

    # Cancel while picking — should succeed
    body = assert_200(client.post(f"/v1/orders/{order['order_id']}/cancel"))
    assert body["status"] == "cancelled"
