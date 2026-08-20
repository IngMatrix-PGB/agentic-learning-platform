"""Tests for explicit CORS configuration (PR-003): the widget's default
allowed origin gets the CORS headers, an unlisted origin does not, and a
preflight OPTIONS request is handled correctly. `allow_origins=["*"]` is
never used — see docs/architecture.md.
"""

from fastapi.testclient import TestClient

ALLOWED_ORIGIN = "http://localhost:8000"
DISALLOWED_ORIGIN = "http://evil.example"


def test_allowed_origin_gets_the_cors_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_disallowed_origin_does_not_get_the_cors_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": DISALLOWED_ORIGIN})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_preflight_for_the_streaming_endpoint_allows_the_configured_origin(
    client: TestClient,
) -> None:
    response = client.options(
        "/v1/query/stream",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_preflight_rejects_a_disallowed_origin(client: TestClient) -> None:
    response = client.options(
        "/v1/query/stream",
        headers={
            "Origin": DISALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )

    assert "access-control-allow-origin" not in response.headers
