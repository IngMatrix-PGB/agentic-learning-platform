"""Tests for the global exception handlers.

These use a throwaway FastAPI app built only inside this test module — the
routes exist purely to trigger each handled exception type on demand and
must never be part of the production app (see
``agentic_learning_platform.app.create_app``, which only wires up the real
``/health`` and ``/ready`` routes).
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_learning_platform.exceptions import AppError, register_exception_handlers


class _NotFoundError(AppError):
    """A concrete `AppError` subclass overriding the default status code."""

    status_code = 404


async def _raise_app_error() -> None:
    raise AppError("something went wrong")


async def _raise_not_found() -> None:
    raise _NotFoundError("resource not found")


async def _validate(count: int) -> dict[str, int]:
    return {"count": count}


async def _raise_unexpected() -> None:
    raise RuntimeError("boom - internal detail that must never leak to the client")


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    # `add_api_route` (rather than the `@app.get(...)` decorator on a nested
    # function) so each handler is passed by reference and pyright doesn't
    # flag it as an unused local closure.
    app.add_api_route("/raise-app-error", _raise_app_error, methods=["GET"])
    app.add_api_route("/raise-not-found", _raise_not_found, methods=["GET"])
    app.add_api_route("/validate", _validate, methods=["GET"])
    app.add_api_route("/raise-unexpected", _raise_unexpected, methods=["GET"])

    return app


@pytest.fixture
def test_app_client() -> Iterator[TestClient]:
    # `raise_server_exceptions=False` is required here: by default TestClient
    # re-raises unhandled server exceptions into the test itself instead of
    # returning the response our global handler produced, which is exactly
    # the behavior under test.
    with TestClient(_build_test_app(), raise_server_exceptions=False) as client:
        yield client


class TestAppError:
    def test_returns_its_default_status_code_and_message(self, test_app_client: TestClient) -> None:
        response = test_app_client.get("/raise-app-error")

        assert response.status_code == 500
        assert response.json() == {"detail": "something went wrong"}

    def test_subclass_can_override_status_code(self, test_app_client: TestClient) -> None:
        response = test_app_client.get("/raise-not-found")

        assert response.status_code == 404
        assert response.json() == {"detail": "resource not found"}


class TestRequestValidationError:
    def test_missing_required_query_param_returns_422(self, test_app_client: TestClient) -> None:
        response = test_app_client.get("/validate")

        assert response.status_code == 422
        body = response.json()
        assert "detail" in body
        assert isinstance(body["detail"], list)
        assert body["detail"][0]["loc"] == ["query", "count"]

    def test_invalid_query_param_type_returns_422(self, test_app_client: TestClient) -> None:
        response = test_app_client.get("/validate", params={"count": "not-a-number"})

        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


class TestUnexpectedException:
    def test_returns_generic_500_with_stable_json_shape(self, test_app_client: TestClient) -> None:
        response = test_app_client.get("/raise-unexpected")

        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}

    def test_does_not_leak_internal_exception_details(self, test_app_client: TestClient) -> None:
        response = test_app_client.get("/raise-unexpected")

        assert "boom" not in response.text
        assert "RuntimeError" not in response.text
        assert "Traceback" not in response.text
