"""FR1 — DC geo-lookup (Haversine).

AC1: GET /v1/dc/lookup?lat=39.95&lon=-75.16 -> 200 with dc_id, name, distance_mi.
     No DC covers location -> 404.
     Missing params -> 422.
"""

from verify.acceptance.conftest import assert_200, assert_404, assert_422


def test_dc_lookup_success(client):
    """Nearest active DC within delivery radius returns 200."""
    body = assert_200(client.get("/v1/dc/lookup", params={"lat": 39.95, "lon": -75.16}))

    assert "dc_id" in body
    assert isinstance(body["dc_id"], str)
    assert len(body["dc_id"]) > 0

    assert "name" in body
    assert isinstance(body["name"], str)

    assert "center_lat" in body
    assert isinstance(body["center_lat"], (int, float))

    assert "center_lon" in body
    assert isinstance(body["center_lon"], (int, float))

    assert "distance_mi" in body
    assert isinstance(body["distance_mi"], (int, float))
    assert body["distance_mi"] >= 0


def test_dc_lookup_no_coverage(client):
    """A location with no DC in delivery radius returns 404."""
    assert_404(client.get("/v1/dc/lookup", params={"lat": 0.0, "lon": 0.0}))


def test_dc_lookup_missing_params(client):
    """Missing lat/lon returns 422."""
    # No query params at all
    assert_422(client.get("/v1/dc/lookup"))

    # lat only — missing lon
    assert_422(client.get("/v1/dc/lookup", params={"lat": "39.95"}))

    # lon only — missing lat
    assert_422(client.get("/v1/dc/lookup", params={"lon": "-75.16"}))


def test_dc_lookup_invalid_params(client):
    """Non-numeric lat/lon returns 422."""
    assert_422(client.get("/v1/dc/lookup", params={"lat": "abc", "lon": "xyz"}))
