"""Tests for the PR-004 authorization context: the DEV-ONLY header provider
in isolation (fast, no HTTP), and the HTTP-level guarantee that all three
scoped endpoints reject a missing/blank context with a stable error before
touching the RAG pipeline at all.
"""

import pytest
from fastapi.testclient import TestClient

from agentic_learning_platform.app import create_app
from agentic_learning_platform.domain.models import RequestContext
from agentic_learning_platform.exceptions import MissingAuthorizationContextError
from agentic_learning_platform.infrastructure.authorization.dev_header_provider import (
    DevHeaderAuthorizationContextProvider,
)


class TestDevHeaderAuthorizationContextProvider:
    def test_resolves_a_valid_context(self) -> None:
        provider = DevHeaderAuthorizationContextProvider()

        context = provider.resolve(organization_id="org-1", course_id="course-1", user_id="user-1")

        assert context == RequestContext(
            organization_id="org-1", course_id="course-1", user_id="user-1"
        )

    @pytest.mark.parametrize(
        "organization_id,course_id,user_id",
        [
            (None, "course-1", "user-1"),
            ("org-1", None, "user-1"),
            ("org-1", "course-1", None),
            ("", "course-1", "user-1"),
            ("org-1", "", "user-1"),
            ("org-1", "course-1", ""),
            (None, None, None),
            ("   ", "course-1", "user-1"),
            ("org-1", "   ", "user-1"),
            ("org-1", "course-1", "   "),
            ("\t\n", "course-1", "user-1"),
            ("org-1", "\t \n", "user-1"),
            ("org-1", "course-1", "\t"),
        ],
    )
    def test_rejects_missing_or_blank_values(
        self, organization_id: str | None, course_id: str | None, user_id: str | None
    ) -> None:
        """Covers, explicitly: absent header, empty string, whitespace-only,
        and tab/newline whitespace — for each of the three fields."""
        provider = DevHeaderAuthorizationContextProvider()

        with pytest.raises(MissingAuthorizationContextError):
            provider.resolve(organization_id=organization_id, course_id=course_id, user_id=user_id)

    def test_normalizes_surrounding_whitespace_on_an_otherwise_valid_value(self) -> None:
        provider = DevHeaderAuthorizationContextProvider()

        context = provider.resolve(
            organization_id="  org-1  ", course_id="\tcourse-1\n", user_id=" user-1 "
        )

        assert context == RequestContext(
            organization_id="org-1", course_id="course-1", user_id="user-1"
        )


@pytest.fixture
def bare_client() -> TestClient:
    """A client with none of conftest's default context headers — for
    exercising the "context missing entirely" path specifically."""
    return TestClient(create_app())


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/v1/documents", {"files": {"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}}),
        ("post", "/v1/query", {"json": {"question": "hola"}}),
        ("post", "/v1/query/stream", {"json": {"question": "hola"}}),
    ],
)
def test_missing_context_returns_a_stable_401_on_every_scoped_endpoint(
    bare_client: TestClient, method: str, path: str, kwargs: dict[str, object]
) -> None:
    with bare_client as client:
        response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401
    assert "detail" in response.json()


def test_blank_header_is_treated_as_missing(bare_client: TestClient) -> None:
    with bare_client as client:
        response = client.post(
            "/v1/query",
            json={"question": "hola"},
            headers={"X-Organization-Id": "", "X-Course-Id": "course-1", "X-User-Id": "user-1"},
        )

    assert response.status_code == 401


def test_whitespace_only_header_is_treated_as_missing(bare_client: TestClient) -> None:
    with bare_client as client:
        response = client.post(
            "/v1/query",
            json={"question": "hola"},
            headers={"X-Organization-Id": "   ", "X-Course-Id": "course-1", "X-User-Id": "user-1"},
        )

    assert response.status_code == 401


def test_body_cannot_contradict_the_authorized_scope(client: TestClient) -> None:
    """`/v1/query`'s body has no organization_id/course_id field at all — an
    attacker-supplied extra field is simply ignored by pydantic, not a
    contradiction to resolve."""
    response = client.post(
        "/v1/query", json={"question": "hola", "organization_id": "attacker-org"}
    )

    assert response.status_code == 200
