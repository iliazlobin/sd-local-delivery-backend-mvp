"""FR6 — Advance order status through lifecycle.

AC6: POST /v1/orders/{order_id}/status {status: "picking"} -> 200.
     Skipping states -> 409.
     Unknown order -> 404.
     Full lifecycle walk: confirmed -> picking -> packed -> en_route -> delivered.
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


def test_advance_status_single_step(client):
    """Advancing from confirmed to picking returns 200."""
    order = _create_test_order(client)

    body = assert_200(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "picking"},
        )
    )
    assert body["status"] == "picking"


def test_advance_status_full_lifecycle(client):
    """Walk the full lifecycle: confirmed -> picking -> packed -> en_route -> delivered."""
    order = _create_test_order(client)

    for expected_status in ("picking", "packed", "en_route", "delivered"):
        body = assert_200(
            client.post(
                f"/v1/orders/{order['order_id']}/status",
                json={"status": expected_status},
            )
        )
        assert body["status"] == expected_status

    # Verify via GET as well
    final = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert final["status"] == "delivered"


def test_advance_status_skip_rejected(client):
    """Skipping a state (confirmed -> packed) returns 409."""
    order = _create_test_order(client)

    assert_409(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "packed"},
        )
    )

    # Order should still be confirmed
    current = assert_200(client.get(f"/v1/orders/{order['order_id']}"))
    assert current["status"] == "confirmed"


def test_advance_status_unknown_order(client):
    """Advancing an unknown order returns 404."""
    fake_id = str(uuid.uuid4())
    assert_404(
        client.post(
            f"/v1/orders/{fake_id}/status",
            json={"status": "picking"},
        )
    )


def test_advance_status_already_delivered(client):
    """Attempting to advance a delivered order returns 409."""
    order = _create_test_order(client)

    # Walk to delivered
    for status in ("picking", "packed", "en_route", "delivered"):
        assert_200(
            client.post(
                f"/v1/orders/{order['order_id']}/status",
                json={"status": status},
            )
        )

    # Try advancing past delivered
    assert_409(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "delivered"},
        )
    )


def test_advance_status_backward_rejected(client):
    """Moving backward (packed -> picking) returns 409."""
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

    # Try going back to picking
    assert_409(
        client.post(
            f"/v1/orders/{order['order_id']}/status",
            json={"status": "picking"},
        )
    )


def test_advance_status_cancelled_order(client):
    """Cannot advance a cancelled order."""
    order = _create_test_order(client)

    # Cancel the order
    assert_200(client.post(f"/v1/orders/{order['order_id']}/cancel"))

    # Try to advance
    resp = client.post(
        f"/v1/orders/{order['order_id']}/status",
        json={"status": "picking"},
    )
    assert (
        resp.status_code == 409
    ), f"Expected 409 for cancelled order, got {resp.status_code}: {resp.text}"
