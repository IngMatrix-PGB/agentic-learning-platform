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


def test_preflight_allows_the_dev_authorization_context_headers(client: TestClient) -> None:
    """PR-004's X-Organization-Id/X-Course-Id/X-User-Id (see
    routes.authorization) must be explicitly allowed by CORS, or a
    cross-origin widget's preflight would be rejected by the browser before
    the request is ever sent — this was previously only checked manually."""
    response = client.options(
        "/v1/query/stream",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Organization-Id, X-Course-Id, X-User-Id",
        },
    )

    allowed_headers = response.headers.get("access-control-allow-headers", "")
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "x-organization-id" in allowed_headers.lower()
    assert "x-course-id" in allowed_headers.lower()
    assert "x-user-id" in allowed_headers.lower()


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
