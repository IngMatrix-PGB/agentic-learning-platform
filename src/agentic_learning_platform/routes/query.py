"""``POST /v1/query`` — ask a question, get an answer with verifiable
citations (or the fixed "insufficient evidence" message)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from agentic_learning_platform.application.services.query_service import QueryService
from agentic_learning_platform.config import get_settings
from agentic_learning_platform.domain.models import Citation, RequestContext
from agentic_learning_platform.routes.authorization import get_request_context

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    """Shared request contract for both ``/v1/query`` and
    ``/v1/query/stream`` — one consistent input validation rule for both,
    not two independently-drifting limits (see docs/architecture.md).

    The max-length check reads ``get_settings()`` inside a validator, not via
    ``Field(max_length=...)``, so it reflects the *current* settings on every
    request/test instead of whatever was cached at module-import time.
    """

    question: str = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def _enforce_max_length(cls, value: str) -> str:
        max_length = get_settings().max_question_length
        if len(value) > max_length:
            raise ValueError(f"question exceeds max_question_length ({max_length})")
        return value


class CitationResponse(BaseModel):
    source: str
    page: int
    chunk_id: UUID
    score: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]


def citation_to_response(citation: Citation) -> CitationResponse:
    """The one place that maps the domain `Citation` to the HTTP contract —
    shared by `/v1/query` and `/v1/query/stream` so the two never drift."""
    return CitationResponse(
        source=citation.source,
        page=citation.page,
        chunk_id=citation.chunk_id,
        score=citation.score,
    )


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


@router.post("/v1/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> QueryResponse:
    result = await query_service.answer(body.question, context)
    return QueryResponse(
        answer=result.answer,
        citations=[citation_to_response(c) for c in result.citations],
    )
