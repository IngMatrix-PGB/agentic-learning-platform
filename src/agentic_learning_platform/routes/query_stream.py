"""``POST /v1/query/stream`` — same question-answering contract as
``/v1/query``, paced progressively over Server-Sent Events.

The full ``QueryAnswer`` (retrieval, evidence check, generation, citations)
is computed **before** the ``StreamingResponse`` is returned — never inside
the async generator. This is deliberate: any error from retrieval,
infrastructure, the answer generator, or input validation must be able to
produce a normal HTTP error status *before* SSE headers are sent, since an
HTTP status can no longer change once streaming has started.

Neither execution mode does real token-by-token model streaming in this PR
(``ExtractiveAnswerGeneratorAdapter`` returns the full text at once;
``BedrockAnswerGeneratorAdapter`` uses ``ainvoke``, not ``astream``). This
endpoint paces the already-complete answer word-by-word purely to
demonstrate the streaming protocol/UX — see docs/architecture.md for why,
and for the future PR that would add real Bedrock streaming behind
``IAnswerGeneratorPort``.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agentic_learning_platform.application.services.query_service import QueryService
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


async def _stream_answer(answer: QueryAnswer) -> AsyncIterator[str]:
    delay_seconds = get_settings().stream_chunk_delay_ms / 1000
    words = answer.answer.split(" ")
    for index, word in enumerate(words):
        text = word if index == len(words) - 1 else f"{word} "
        yield _sse_event("token", {"text": text})
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)

    citations = [citation_to_response(c).model_dump(mode="json") for c in answer.citations]
    yield _sse_event("citations", {"citations": citations})
    yield _sse_event("done", {})


async def _stream_answer_with_error_guard(answer: QueryAnswer) -> AsyncIterator[str]:
    # Defensive only: the RAG pipeline already ran to completion before this
    # generator starts (see module docstring), so this guards against
    # unexpected failures during the emission itself (e.g. the client
    # disconnecting mid-pace), not against retrieval/generation errors.
    # `asyncio.CancelledError` (e.g. from a client disconnect) is a
    # `BaseException`, not caught here — it propagates normally instead of
    # being reported as an "error" event on a connection that is already gone.
    try:
        async for chunk in _stream_answer(answer):
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
    # Runs to completion here, outside the generator — see module docstring.
    answer = await query_service.answer(body.question, context)
    return StreamingResponse(
        _stream_answer_with_error_guard(answer), media_type="text/event-stream"
    )
