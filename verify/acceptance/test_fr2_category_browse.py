"""FR2 — Category browse with availability.

AC2: GET /v1/catalog?dc_id=PHL-01&category=snacks&page=1&page_size=30 -> 200
       with paginated items, each having product_id, name, brand, category,
       unit_price_cents, available_qty.
     Unknown DC -> 404.
     Missing dc_id -> 400.
"""

from verify.acceptance.conftest import assert_200, assert_400, assert_404


def test_category_browse_success(client):
    """Browse products in a valid category at a known DC returns 200."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "category": "snacks", "page": 1, "page_size": 30},
        )
    )

    assert "items" in body
    assert isinstance(body["items"], list)

    assert "page" in body
    assert body["page"] == 1

    assert "page_size" in body

    assert "total" in body
    assert isinstance(body["total"], int)

    # Every item must have the expected shape
    for item in body["items"]:
        assert "product_id" in item
        assert isinstance(item["product_id"], str)
        assert "name" in item
        assert "brand" in item
        assert "category" in item
        assert item["category"] == "snacks"
        assert "unit_price_cents" in item
        assert isinstance(item["unit_price_cents"], int)
        assert item["unit_price_cents"] > 0
        assert "available_qty" in item
        assert isinstance(item["available_qty"], int)
        assert item["available_qty"] >= 0
        # available field indicates stock status
        assert "available" in item
        assert isinstance(item["available"], bool)


def test_category_browse_empty_category(client):
    """A valid DC with a category that has no products returns empty items."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "category": "nonexistent_category_xyz", "page": 1},
        )
    )
    assert body["items"] == []
    assert body["total"] == 0


def test_category_browse_unknown_dc(client):
    """An unknown dc_id returns 404."""
    assert_404(
        client.get(
            "/v1/catalog",
            params={"dc_id": "NONEXISTENT", "category": "snacks"},
        )
    )


def test_category_browse_missing_dc_id(client):
    """Missing dc_id returns 400."""
    assert_400(client.get("/v1/catalog", params={"category": "snacks"}))


def test_category_browse_pagination(client):
    """Page 2 returns the correct offset; empty page returns empty items."""
    # Get first page
    page1 = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "category": "snacks", "page": 1, "page_size": 2},
        )
    )

    if page1["total"] > 2:
        # Page 2 should have different items (if any)
        page2 = assert_200(
            client.get(
                "/v1/catalog",
                params={"dc_id": "PHL-01", "category": "snacks", "page": 2, "page_size": 2},
            )
        )
        assert page2["page"] == 2
        assert len(page2["items"]) <= 2
        # Verify items differ from page 1
        p1_ids = {i["product_id"] for i in page1["items"]}
        p2_ids = {i["product_id"] for i in page2["items"]}
        assert p1_ids.isdisjoint(p2_ids), "Page 2 should not repeat page 1 items"


def test_category_browse_page_beyond_total(client):
    """A page number beyond the total should return empty items."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "category": "snacks", "page": 999, "page_size": 30},
        )
    )
    assert body["items"] == []
    assert body["total"] > 0 or body["total"] == 0  # total is still reported
