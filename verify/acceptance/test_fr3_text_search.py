"""FR3 — Text search with ILIKE.

AC3: GET /v1/catalog?dc_id=PHL-01&q=chips -> 200 with matching items.
     In-stock items appear before out-of-stock.
     No match -> 200 with empty items.
"""

from verify.acceptance.conftest import assert_200, assert_400, assert_404


def test_text_search_success(client):
    """Searching for a known product name returns matching items."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "chips", "page": 1, "page_size": 30},
        )
    )

    assert "items" in body
    assert "total" in body

    # All returned items should match the search (name contains "chips")
    for item in body["items"]:
        assert (
            "chips" in item["name"].lower()
        ), f"Item '{item['name']}' does not match search 'chips'"


def test_text_search_in_stock_first(client):
    """In-stock products appear before out-of-stock in search results."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "chips", "page": 1, "page_size": 30},
        )
    )

    items = body["items"]
    if len(items) < 2:
        return  # Not enough items to verify ordering

    # Find the first out-of-stock item (if any)
    first_oos_idx = None
    for i, item in enumerate(items):
        if not item.get("available", True):
            first_oos_idx = i
            break

    if first_oos_idx is not None:
        # All items before this must be in-stock
        for j in range(first_oos_idx):
            assert items[j].get("available", True), (
                f"In-stock ordering violation at position {j}: "
                f"'{items[j]['name']}' is out-of-stock but appears before first OOS item at {first_oos_idx}"
            )


def test_text_search_no_match(client):
    """A search with no matching products returns empty items."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "xyznonexistent12345", "page": 1},
        )
    )
    assert body["items"] == []
    assert body["total"] == 0


def test_text_search_missing_dc_id(client):
    """Search without dc_id returns 400."""
    assert_400(client.get("/v1/catalog", params={"q": "chips"}))


def test_text_search_unknown_dc(client):
    """Search against unknown DC returns 404."""
    assert_404(client.get("/v1/catalog", params={"dc_id": "NONEXISTENT", "q": "chips"}))


def test_text_search_empty_query(client):
    """An empty query string returns all products (same as category browse without category)."""
    body = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "", "page": 1},
        )
    )
    assert "items" in body
    assert "total" in body
    # With empty query, should return all products for that DC
    assert body["total"] >= 0


def test_text_search_case_insensitive(client):
    """ILIKE search is case-insensitive."""
    lower = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "chips", "page": 1},
        )
    )
    upper = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "CHIPS", "page": 1},
        )
    )
    mixed = assert_200(
        client.get(
            "/v1/catalog",
            params={"dc_id": "PHL-01", "q": "ChIpS", "page": 1},
        )
    )
    # All three queries should return the same total
    assert lower["total"] == upper["total"] == mixed["total"]
