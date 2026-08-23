"""``POST /v1/query/stream`` — same question-answering contract as
``/v1/query``, delivered progressively over Server-Sent Events.

PR-008 changed how this endpoint delivers its answer, but not the
orchestration that produces it: retrieval, the evidence decision,
generation, and citation construction still happen in exactly the same
LangGraph nodes ``/v1/query`` uses (see ``application.workflows.query_graph``
and ``QueryService.answer_stream``) — this route only translates the
graph's progressive output into SSE frames.

Exception semantics changed as a deliberate, approved trade-off (see
docs/architecture.md's PR-008 section): retrieval now runs *inside* the
same streamed graph execution that has already opened this
``StreamingResponse``, so a retrieval or generation failure can no longer
produce a clean pre-SSE HTTP error status the way it could before real
model streaming existed. Any such failure is instead reported as an
``event: error`` SSE frame (the existing error guard below, now covering
graph execution, not just the emission step) — the original exception is
never swallowed, only translated into that established SSE error contract.
Retrieval is deliberately NOT run outside the graph merely to preserve the
old pre-stream HTTP status: that would mean two different orchestration
implementations for ``/v1/query`` and ``/v1/query/stream``, which is
exactly what PR-007/PR-008 exist to avoid.

Local mode paces each token with ``stream_chunk_delay_ms`` for UX/protocol
demo purposes (``ExtractiveAnswerGeneratorAdapter`` has no real incremental
generation latency of its own). AWS mode adds no artificial delay — real
Bedrock token latency is the pacing.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agentic_learning_platform.application.services.query_service import QueryService
from agentic_learning_platform.application.workflows.query_graph import QueryStreamToken
from agentic_learning_platform.config import get_settings
from agentic_learning_platform.domain.models import QueryAnswer, RequestContext
from agentic_learning_platform.routes.authorization import get_request_context
from agentic_learning_platform.routes.query import (
    QueryRequest,
    citation_to_response,
    get_query_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_answer(
    query_service: QueryService, question: str, context: RequestContext
) -> AsyncIterator[str]:
    # Applied only in local mode: AWS/Bedrock chunks are real progressive
    # generation and must not be artificially slowed down.
    delay_seconds = (
        get_settings().stream_chunk_delay_ms / 1000 if get_settings().runtime_mode == "local" else 0
    )

    async for item in query_service.answer_stream(question, context):
        if isinstance(item, QueryStreamToken):
            yield _sse_event("token", {"text": item.text})
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            continue

        answer: QueryAnswer = item
        citations = [citation_to_response(c).model_dump(mode="json") for c in answer.citations]
        yield _sse_event("citations", {"citations": citations})
        yield _sse_event("done", {})


async def _stream_answer_with_error_guard(
    query_service: QueryService, question: str, context: RequestContext
) -> AsyncIterator[str]:
    # Covers the full graph execution now (retrieval, evidence decision,
    # generation), not just the emission step — see this module's
    # docstring. The original exception is logged, never swallowed; it
    # cannot become an HTTP error status at this point (SSE headers were
    # already sent), so it is translated into the established `error` SSE
    # event instead. `asyncio.CancelledError` (e.g. a client disconnect) is
    # a `BaseException`, not caught here — it propagates normally instead
    # of being reported as an "error" event on a connection that is
    # already gone.
    try:
        async for chunk in _stream_answer(query_service, question, context):
            yield chunk
    except Exception:
        logger.exception("Unexpected error while streaming a query answer")
        yield _sse_event("error", {"message": "stream_interrupted"})


@router.post("/v1/query/stream")
async def query_stream(
    body: QueryRequest,
    query_service: Annotated[QueryService, Depends(get_query_service)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream_answer_with_error_guard(query_service, body.question, context),
        media_type="text/event-stream",
    )
