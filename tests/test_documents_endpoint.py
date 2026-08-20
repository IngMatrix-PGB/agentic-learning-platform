"""Tests for POST /v1/documents (against the real stack: Docling, the
configured embedding adapter, and Postgres — nothing here is mocked)."""

from uuid import UUID

import asyncpg
from fastapi.testclient import TestClient

from agentic_learning_platform.config import get_settings


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


async def test_upload_associates_the_document_with_the_authorized_scope(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    headers = {
        "X-Organization-Id": "org-assoc-test",
        "X-Course-Id": "course-assoc-test",
        "X-User-Id": "user-assoc-test",
    }

    response = client.post(
        "/v1/documents",
        files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 200
    document_id = response.json()["document_id"]

    conn = await asyncpg.connect(dsn=get_settings().database_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT organization_id, course_id FROM source_documents WHERE id = $1",
            UUID(document_id),
        )
    finally:
        await conn.close()

    assert row is not None
    assert row["organization_id"] == "org-assoc-test"
    assert row["course_id"] == "course-assoc-test"


def test_same_checksum_can_exist_in_different_scopes(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    course_a_headers = {
        "X-Organization-Id": "org-scope-test",
        "X-Course-Id": "course-scope-A",
        "X-User-Id": "user-1",
    }
    course_b_headers = {
        "X-Organization-Id": "org-scope-test",
        "X-Course-Id": "course-scope-B",
        "X-User-Id": "user-2",
    }

    first = client.post(
        "/v1/documents",
        files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")},
        headers=course_a_headers,
    )
    second = client.post(
        "/v1/documents",
        files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")},
        headers=course_b_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["already_existed"] is False
    assert second.json()["already_existed"] is False
    assert first.json()["document_id"] != second.json()["document_id"]
