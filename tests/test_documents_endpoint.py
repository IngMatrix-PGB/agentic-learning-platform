"""Tests for POST /v1/documents (against the real stack: Docling, the
configured embedding adapter, and Postgres — nothing here is mocked)."""

from fastapi.testclient import TestClient


def test_upload_creates_a_document_with_its_chunks(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    response = client.post(
        "/v1/documents",
        files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["pages"] == 2
    assert body["chunks_created"] >= 2
    assert body["already_existed"] is False


def test_uploading_the_same_file_twice_is_idempotent(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    first = client.post(
        "/v1/documents", files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")}
    )
    second = client.post(
        "/v1/documents", files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["document_id"] == second.json()["document_id"]
    assert second.json()["already_existed"] is True
    assert second.json()["chunks_created"] == 0


def test_rejects_non_pdf_uploads(client: TestClient) -> None:
    response = client.post(
        "/v1/documents",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )

    assert response.status_code == 400
