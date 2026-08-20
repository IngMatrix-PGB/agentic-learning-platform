"""Adversarial tests for PR-004 corpus isolation, specifically exercising
the Hybrid Retrieval path added in PR-006 (vector + lexical + RRF) — the
non-negotiable isolation property from `tests/test_corpus_isolation.py` must
hold identically here: no branch of the pipeline (vector, lexical, or the
fused result) may ever surface another organization's/course's chunks, even
with byte-identical content and embeddings across scopes.
"""

import os
import uuid
from collections.abc import Iterable, Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_learning_platform.app import create_app
from agentic_learning_platform.config import get_settings

KNOWN_QUESTION = "¿Qué es la gestión de incidentes?"


@pytest.fixture
def hybrid_client() -> Iterator[TestClient]:
    """Same shape as `conftest.py`'s `client` fixture, but with
    `RETRIEVAL_STRATEGY=hybrid` forced for this app instance only — the
    default app used by every other test stays vector_only."""
    os.environ["RETRIEVAL_STRATEGY"] = "hybrid"
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as test_client:
            yield test_client
    finally:
        del os.environ["RETRIEVAL_STRATEGY"]
        get_settings.cache_clear()


def _scope_headers(run_id: str, *, org: str, course: str, user: str) -> dict[str, str]:
    return {
        "X-Organization-Id": f"{org}-{run_id}",
        "X-Course-Id": f"{course}-{run_id}",
        "X-User-Id": user,
    }


def _upload(client: TestClient, headers: dict[str, str], pdf_bytes: bytes) -> str:
    response = client.post(
        "/v1/documents",
        files={"file": ("manual.pdf", pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["already_existed"] is False
    return str(body["document_id"])


def _query_citation_chunk_ids(
    client: TestClient, headers: dict[str, str], *, question: str = KNOWN_QUESTION
) -> set[str]:
    response = client.post("/v1/query", json={"question": question}, headers=headers)
    assert response.status_code == 200
    return {citation["chunk_id"] for citation in response.json()["citations"]}


def _assert_pairwise_disjoint(*chunk_id_sets: Iterable[str]) -> None:
    sets = [set(s) for s in chunk_id_sets]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert sets[i].isdisjoint(sets[j]), (
                f"scope {i} and scope {j} share chunk_id(s): {sets[i] & sets[j]}"
            )


def test_hybrid_retrieval_never_cross_contaminates_identical_content_across_three_scopes(
    hybrid_client: TestClient, sample_pdf_bytes: bytes
) -> None:
    run_id = uuid.uuid4().hex[:8]
    org_a_course_a = _scope_headers(run_id, org="org-A", course="course-A", user="user-1")
    org_a_course_b = _scope_headers(run_id, org="org-A", course="course-B", user="user-2")
    org_b_course_a = _scope_headers(run_id, org="org-B", course="course-A", user="user-3")

    doc_aa = _upload(hybrid_client, org_a_course_a, sample_pdf_bytes)
    doc_ab = _upload(hybrid_client, org_a_course_b, sample_pdf_bytes)
    doc_ba = _upload(hybrid_client, org_b_course_a, sample_pdf_bytes)
    assert len({doc_aa, doc_ab, doc_ba}) == 3

    chunk_ids_aa = _query_citation_chunk_ids(hybrid_client, org_a_course_a)
    chunk_ids_ab = _query_citation_chunk_ids(hybrid_client, org_a_course_b)
    chunk_ids_ba = _query_citation_chunk_ids(hybrid_client, org_b_course_a)

    assert chunk_ids_aa, "expected citations when querying org-A/course-A"
    assert chunk_ids_ab, "expected citations when querying org-A/course-B"
    assert chunk_ids_ba, "expected citations when querying org-B/course-A"

    _assert_pairwise_disjoint(chunk_ids_aa, chunk_ids_ab, chunk_ids_ba)


def test_hybrid_retrieval_lexical_branch_is_also_scoped(
    hybrid_client: TestClient, sample_pdf_bytes: bytes
) -> None:
    """Specifically targets the lexical/PostgreSQL-FTS branch: a question
    phrased to maximize keyword overlap (not just embedding similarity)
    must still never surface another course's chunk_ids."""
    run_id = uuid.uuid4().hex[:8]
    course_a_headers = _scope_headers(run_id, org="org-A", course="course-A", user="user-1")
    course_b_headers = _scope_headers(run_id, org="org-A", course="course-B", user="user-2")

    _upload(hybrid_client, course_a_headers, sample_pdf_bytes)
    _upload(hybrid_client, course_b_headers, sample_pdf_bytes)

    chunk_ids_a = _query_citation_chunk_ids(
        hybrid_client, course_a_headers, question="gestion de incidentes"
    )
    chunk_ids_b = _query_citation_chunk_ids(
        hybrid_client, course_b_headers, question="gestion de incidentes"
    )

    assert chunk_ids_a, "expected citations when querying course-A"
    assert chunk_ids_b, "expected citations when querying course-B"
    assert chunk_ids_a.isdisjoint(chunk_ids_b)
