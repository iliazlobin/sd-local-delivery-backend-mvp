"""Shared fixtures and helpers for the black-box acceptance suite.

These tests do NOT import the app. They talk to the running system via HTTP
at API_BASE_URL.
"""

import os
import time

import httpx
import pytest

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def base_url():
    """Base URL of the running application under test."""
    return API_BASE_URL


@pytest.fixture(scope="session")
def client(base_url):
    """Session-scoped httpx client with a 10-second timeout."""
    with httpx.Client(base_url=base_url, timeout=10.0) as c:
        # Wait for the server to be ready (up to 30 seconds)
        _wait_for_healthz(c)
        yield c


def _wait_for_healthz(client: httpx.Client, max_wait: int = 30):
    """Poll /healthz until the server responds 200 or max_wait seconds elapse."""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            r = client.get("/healthz")
            if r.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(1)
    raise RuntimeError(f"Server did not become healthy within {max_wait}s")


# ── Assertion helpers ──────────────────────────────────────────────


def assert_200(r, expected_status=200):
    """Assert status code and return parsed JSON."""
    assert (
        r.status_code == expected_status
    ), f"Expected {expected_status}, got {r.status_code}: {r.text}"
    return r.json()


def assert_201(r):
    """Assert 201 Created and return parsed JSON."""
    return assert_200(r, 201)


def assert_400(r):
    """Assert 400 Bad Request and return parsed body."""
    assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
    try:
        return r.json()
    except Exception:
        return {"detail": r.text}


def assert_404(r):
    """Assert 404 Not Found and return parsed body."""
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
    try:
        return r.json()
    except Exception:
        return {"detail": r.text}


def assert_409(r):
    """Assert 409 Conflict and return parsed body."""
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
    try:
        return r.json()
    except Exception:
        return {"detail": r.text}


def assert_422(r):
    """Assert 422 Unprocessable Entity and return parsed body."""
    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    try:
        return r.json()
    except Exception:
        return {"detail": r.text}
