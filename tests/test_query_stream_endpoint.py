"""Tests for POST /v1/query/stream — same question-answering contract as
/v1/query (PR-002), paced over SSE. Verifies event order, that the
concatenated tokens reconstruct the same answer /v1/query would return, that
citations carry the structured fields (never inferred from text), and that
input validation happens before the stream opens.
"""

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_learning_platform.application.services.query_service import NO_EVIDENCE_MESSAGE
from agentic_learning_platform.config import get_settings


# Pytest discovers and invokes autouse fixtures by name via its plugin
# machinery (see the same pattern/comment on conftest.py's
# `_clear_settings_cache`), so pyright has no way to see this as "used".
@pytest.fixture(autouse=True)
def _fast_stream(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setenv("STREAM_CHUNK_DELAY_MS", "0")
    # Explicit clear (not just relying on fixture-instantiation order): the
    # `client` fixture may already have called get_settings() — via
    # create_app()/lifespan — before this fixture ran and cached the default
    # delay. `get_settings` is read fresh on every request in
    # routes.query_stream, so clearing here guarantees the request made in
    # the test body sees this env var, regardless of instantiation order.
    get_settings.cache_clear()


def _upload_sample_document(client: TestClient, sample_pdf_bytes: bytes) -> None:
    response = client.post(
        "/v1/documents", files={"file": ("manual.pdf", sample_pdf_bytes, "application/pdf")}
    )
    assert response.status_code == 200


def _parse_sse_events(raw_text: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in raw_text.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        event_type = "message"
        data_line = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_line += line.removeprefix("data:").strip()
        events.append((event_type, json.loads(data_line)))
    return events


def _stream(client: TestClient, question: str) -> Iterator[str]:
    with client.stream("POST", "/v1/query/stream", json={"question": question}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        yield from response.iter_text()


def test_stream_event_order_is_token_then_citations_then_done(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    _upload_sample_document(client, sample_pdf_bytes)

    raw_text = "".join(_stream(client, "¿Qué es la gestión de incidentes?"))
    events = _parse_sse_events(raw_text)

    event_types = [event_type for event_type, _ in events]
    assert event_types[-2:] == ["citations", "done"]
    assert all(event_type == "token" for event_type in event_types[:-2])
    assert len(event_types) > 2, "expected at least one token before citations/done"


def test_stream_reconstructs_the_same_answer_as_non_streaming_query(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    _upload_sample_document(client, sample_pdf_bytes)
    question = "¿Qué es la gestión de incidentes?"

    non_streaming = client.post("/v1/query", json={"question": question})
    assert non_streaming.status_code == 200
    expected_answer = non_streaming.json()["answer"]

    raw_text = "".join(_stream(client, question))
    events = _parse_sse_events(raw_text)

    reconstructed = "".join(
        str(data["text"]) for event_type, data in events if event_type == "token"
    )
    assert reconstructed == expected_answer


def test_stream_citations_carry_the_structured_fields(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    _upload_sample_document(client, sample_pdf_bytes)

    raw_text = "".join(_stream(client, "¿Qué es la gestión de incidentes?"))
    events = _parse_sse_events(raw_text)

    citations_events = [data for event_type, data in events if event_type == "citations"]
    assert len(citations_events) == 1
    citations = citations_events[0]["citations"]
    assert isinstance(citations, list)
    assert citations[0]["source"] == "manual.pdf"
    assert citations[0]["page"] == 1
    assert "chunk_id" in citations[0]
    assert 0.0 <= citations[0]["score"] <= 1.0


def test_stream_out_of_scope_question_ends_with_empty_citations(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    _upload_sample_document(client, sample_pdf_bytes)

    raw_text = "".join(_stream(client, "¿Cómo se prepara una paella valenciana?"))
    events = _parse_sse_events(raw_text)

    reconstructed = "".join(
        str(data["text"]) for event_type, data in events if event_type == "token"
    )
    assert reconstructed == NO_EVIDENCE_MESSAGE

    citations_events = [data for event_type, data in events if event_type == "citations"]
    assert citations_events == [{"citations": []}]
    assert events[-1][0] == "done"


def test_stream_rejects_an_empty_question_before_opening_the_stream(client: TestClient) -> None:
    response = client.post("/v1/query/stream", json={"question": ""})
    assert response.status_code == 422


def test_stream_rejects_a_question_longer_than_max_question_length(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_QUESTION_LENGTH", "10")
    get_settings.cache_clear()  # see _fast_stream fixture above for why
    response = client.post("/v1/query/stream", json={"question": "a" * 11})
    assert response.status_code == 422


def test_stream_accepts_a_question_exactly_at_max_question_length(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_QUESTION_LENGTH", "10")
    get_settings.cache_clear()  # see _fast_stream fixture above for why
    response = client.post("/v1/query/stream", json={"question": "a" * 10})
    assert response.status_code == 200


def test_existing_query_endpoint_still_works_unchanged(
    client: TestClient, sample_pdf_bytes: bytes
) -> None:
    """Regression guard: touching the shared QueryRequest model must not
    change /v1/query's behavior for a normal, in-limit question."""
    _upload_sample_document(client, sample_pdf_bytes)

    response = client.post("/v1/query", json={"question": "¿Qué es la gestión de incidentes?"})

    assert response.status_code == 200
    assert response.json()["citations"]
