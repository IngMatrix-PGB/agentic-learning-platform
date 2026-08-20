"""Adversarial tests for PR-004 corpus isolation.

Identical PDF bytes are uploaded into three different (organization, course)
scopes — org_A/course_A, org_A/course_B, org_B/course_A — so their extracted
text, chunking, and FastEmbed embeddings are byte-for-byte identical. This is
deliberately the hardest case: with identical embeddings, an unscoped or
incorrectly-scoped `ORDER BY embedding <=> $1 LIMIT $2` would tie on
similarity score and could easily let another scope's chunks slip into the
top-k results. The property under test is checked by chunk_id/citation
identity, never by HTTP status alone.
"""

import uuid
from collections.abc import Iterable

from fastapi.testclient import TestClient

KNOWN_QUESTION = "¿Qué es la gestión de incidentes?"


def _scope_headers(run_id: str, *, org: str, course: str, user: str) -> dict[str, str]:
    # `run_id` (unique per test function call) keeps this test's scopes from
    # colliding with another test function's identically-named org-A/course-A
    # in the same session-shared ephemeral test database (see conftest.py) —
    # without it, scoped checksum idempotency would make a later test's
    # upload return `already_existed=True` for what it expects to be a fresh
    # document.
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


def _stream_citation_chunk_ids(
    client: TestClient, headers: dict[str, str], *, question: str = KNOWN_QUESTION
) -> set[str]:
    import json as json_module

    with client.stream(
        "POST", "/v1/query/stream", json={"question": question}, headers=headers
    ) as response:
        assert response.status_code == 200
        raw_text = "".join(response.iter_text())

    for block in raw_text.strip("\n").split("\n\n"):
        if not block.startswith("event: citations"):
            continue
        data_line = next(line for line in block.split("\n") if line.startswith("data:"))
        payload = json_module.loads(data_line.removeprefix("data:").strip())
        return {citation["chunk_id"] for citation in payload["citations"]}
    raise AssertionError("no 'citations' event found in the SSE stream")


def _assert_pairwise_disjoint(*chunk_id_sets: Iterable[str]) -> None:
    sets = [set(s) for s in chunk_id_sets]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            assert sets[i].isdisjoint(sets[j]), (
                f"scope {i} and scope {j} share chunk_id(s): {sets[i] & sets[j]}"
            )


def test_identical_content_in_three_scopes_never_cross_contaminates(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    run_id = uuid.uuid4().hex[:8]
    org_a_course_a = _scope_headers(run_id, org="org-A", course="course-A", user="user-1")
    org_a_course_b = _scope_headers(run_id, org="org-A", course="course-B", user="user-2")
    org_b_course_a = _scope_headers(run_id, org="org-B", course="course-A", user="user-3")

    doc_aa = _upload(client, org_a_course_a, sample_pdf_bytes)
    doc_ab = _upload(client, org_a_course_b, sample_pdf_bytes)
    doc_ba = _upload(client, org_b_course_a, sample_pdf_bytes)

    # Scoped idempotency (decision #4): identical bytes are three distinct
    # documents, one per scope, not a single globally-deduplicated one.
    assert len({doc_aa, doc_ab, doc_ba}) == 3

    chunk_ids_aa = _query_citation_chunk_ids(client, org_a_course_a)
    chunk_ids_ab = _query_citation_chunk_ids(client, org_a_course_b)
    chunk_ids_ba = _query_citation_chunk_ids(client, org_b_course_a)

    assert chunk_ids_aa, "expected citations when querying org-A/course-A"
    assert chunk_ids_ab, "expected citations when querying org-A/course-B"
    assert chunk_ids_ba, "expected citations when querying org-B/course-A"

    # The core property, both directions at once: no pair of scopes shares a
    # single chunk_id, despite identical source text and embeddings —
    # course isolation (A vs B within org A) AND organization isolation
    # (org A vs org B, same course_id string "course-A" reused across orgs).
    _assert_pairwise_disjoint(chunk_ids_aa, chunk_ids_ab, chunk_ids_ba)


def test_query_stream_respects_the_exact_same_scope_as_query(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    run_id = uuid.uuid4().hex[:8]
    course_a_headers = _scope_headers(run_id, org="org-A", course="course-A", user="user-1")
    course_b_headers = _scope_headers(run_id, org="org-A", course="course-B", user="user-2")

    _upload(client, course_a_headers, sample_pdf_bytes)
    _upload(client, course_b_headers, sample_pdf_bytes)

    non_streaming_chunk_ids = _query_citation_chunk_ids(client, course_a_headers)
    streaming_chunk_ids = _stream_citation_chunk_ids(client, course_a_headers)
    other_course_chunk_ids = _query_citation_chunk_ids(client, course_b_headers)

    assert streaming_chunk_ids == non_streaming_chunk_ids
    assert streaming_chunk_ids.isdisjoint(other_course_chunk_ids)
