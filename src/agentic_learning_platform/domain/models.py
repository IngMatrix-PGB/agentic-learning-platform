"""Domain models for the local RAG flow.

Plain, framework-free dataclasses — distinct from the HTTP request/response
models that live next to the routes. A route's Pydantic DTO is mapped to/from
these, never passed directly into a service.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A single uploaded document, identified by the checksum of its bytes
    (scoped to its organization/course — see docs/architecture.md's PR-004
    section: the same bytes can exist as separate documents in different
    courses)."""

    id: UUID
    organization_id: str
    course_id: str
    source_name: str
    checksum_sha256: str
    mime_type: str
    file_size: int
    page_count: int
    processing_status: Literal["completed", "failed"]
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A single chunk of extracted text, tied to the page it came from.

    ``organization_id``/``course_id`` are denormalized here from the parent
    ``SourceDocument`` (not just present on it) so retrieval can filter
    directly on this table before ``ORDER BY ... LIMIT`` — see
    ``PgVectorStoreAdapter.search`` and docs/architecture.md's PR-004
    section for why a JOIN-based filter would not work as well with
    pgvector's ANN index. Always written from the same ``SourceDocument`` in
    the same transaction (``insert_document``), so it can never diverge from
    its parent document's scope.
    """

    id: UUID
    document_id: UUID
    organization_id: str
    course_id: str
    source_name: str
    page_number: int
    chunk_index: int
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A raw vector-store hit, before it is turned into a `Citation`."""

    chunk_id: UUID
    document_id: UUID
    source_name: str
    page_number: int
    chunk_index: int
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class Citation:
    """A verifiable source reference attached to an answer.

    Only `source`, `page`, `chunk_id` and `score` are exposed in this PR's API
    response. `extra` exists so future PRs (DOCX section, PPTX slide, video
    timestamp, ...) can attach format-specific metadata without changing this
    type's shape or the response contract established here.
    """

    source: str
    page: int
    chunk_id: UUID
    score: float
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class QueryAnswer:
    """The result of answering a question against the ingested corpus."""

    answer: str
    citations: list[Citation]
    has_sufficient_evidence: bool


@dataclass(frozen=True, slots=True)
class RequestContext:
    """The authorization scope of an incoming request.

    IDs are treated as opaque strings, not UUID: the real values will come
    from an external identity provider (Cognito/OIDC/an LMS) whose ID format
    is not yet known — forcing UUID here would risk rejecting legitimate
    external IDs before that decision is made (see docs/architecture.md's
    PR-004 section). ``user_id`` identifies the acting user for logging/audit
    only; it never participates in the corpus scope filter (that is
    ``organization_id``/``course_id`` alone — see ``RetrievalService``).
    """

    organization_id: str
    course_id: str
    user_id: str
