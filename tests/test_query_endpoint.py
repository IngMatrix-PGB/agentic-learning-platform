"""Tests for POST /v1/query — the central acceptance criteria of PR-002:
a known question returns a citation with the correct page, and an
out-of-scope question returns the fixed "insufficient evidence" message
without ever calling the answer generator.
"""

from fastapi.testclient import TestClient

from agentic_learning_platform.application.services.query_service import NO_EVIDENCE_MESSAGE


def _upload_sample_document(client: TestClient, sample_pdf_bytes: bytes) -> None:
    response = client.post(
        "/v1/documents", files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 200


def test_known_question_returns_a_citation_with_the_correct_page(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    _upload_sample_document(client, sample_pdf_bytes)

    response = client.post("/v1/query", json={"question": "¿Qué es la gestión de incidentes?"})

    assert response.status_code == 200
    body = response.json()
    assert body["citations"], "expected at least one citation for a known-content question"
    assert body["citations"][0]["source"] == "manual.pdf"
    assert body["citations"][0]["page"] == 1
    assert 0.0 <= body["citations"][0]["score"] <= 1.0
    assert body["answer"]


def test_out_of_scope_question_returns_the_fixed_no_evidence_message(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    _upload_sample_document(client, sample_pdf_bytes)

    response = client.post(
        "/v1/query", json={"question": "¿Cómo se prepara una paella valenciana?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == NO_EVIDENCE_MESSAGE
    assert body["citations"] == []
