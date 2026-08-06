"""``POST /v1/query`` — ask a question, get an answer with verifiable
citations (or the fixed "insufficient evidence" message)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from agentic_learning_platform.application.services.query_service import QueryService

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    question: str


class CitationResponse(BaseModel):
    source: str
    page: int
    chunk_id: UUID
    score: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationResponse]


def get_query_service(request: Request) -> QueryService:
    return request.app.state.query_service


@router.post("/v1/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    query_service: Annotated[QueryService, Depends(get_query_service)],
) -> QueryResponse:
    result = await query_service.answer(body.question)
    return QueryResponse(
        answer=result.answer,
        citations=[
            CitationResponse(source=c.source, page=c.page, chunk_id=c.chunk_id, score=c.score)
            for c in result.citations
        ],
    )
