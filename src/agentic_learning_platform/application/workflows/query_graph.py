"""LangGraph orchestration for the query-answering workflow (PR-007).

This module is a pure orchestration seam: every node delegates to the
existing ``RetrievalService`` / ``IAnswerGeneratorPort`` for all actual
business logic. No retrieval, evidence-threshold, or generation logic is
reimplemented here — ``RetrievalService`` remains the single source of
truth for ``has_sufficient_evidence`` (see ADR-0002).
``evaluate_evidence`` only observes and logs that decision; it never
recomputes it, and introduces no new evidence policy.

No checkpointer is configured: the compiled graph handles one request at a
time, with no persisted or conversational state (see
docs/OPEN_SOURCE_DISCOVERY.md — persistent checkpointing is deferred until
a real conversational-persistence requirement exists). A
``CompiledStateGraph`` built this way is reentrant and holds no per-request
mutable state of its own, so a single instance is safe to share across
concurrent requests, exactly like the ``RetrievalService`` and
``IAnswerGeneratorPort`` it wraps.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, cast

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.domain.models import Citation, RequestContext, SearchResult

NO_EVIDENCE_MESSAGE = "No hay información suficiente en el contenido disponible."

logger = logging.getLogger(__name__)

QueryGraph = CompiledStateGraph["QueryGraphState", None, "QueryGraphState", "QueryGraphState"]


@dataclass(slots=True)
class QueryGraphState:
    """Per-request graph state, populated incrementally node by node (see
    docs/architecture.md's PR-007 section for producer/consumer per field).

    Never persisted (no checkpointer — see module docstring): this is a
    single-request, in-memory structure only.
    """

    question: str
    request_context: RequestContext
    retrieval_results: list[SearchResult] = field(default_factory=list[SearchResult])
    has_sufficient_evidence: bool = False
    answer: str | None = None
    citations: list[Citation] = field(default_factory=list[Citation])


def _to_citation(result: SearchResult) -> Citation:
    """The one implementation of SearchResult -> Citation mapping, reused
    exclusively from ``build_citations`` below — citations are derived only
    from retrieved evidence, never from generated text."""
    return Citation(
        source=result.source_name,
        page=result.page_number,
        chunk_id=result.chunk_id,
        score=result.score,
    )


def build_query_graph(
    retrieval_service: RetrievalService,
    answer_generator_port: IAnswerGeneratorPort,
) -> QueryGraph:
    """Build and compile the query graph once (see ``app.py``'s
    ``_lifespan`` — never per request). ``retrieval_service`` and
    ``answer_generator_port`` are the exact same instances the rest of the
    application already uses; nothing here constructs its own copy."""

    async def retrieve(state: QueryGraphState) -> dict[str, object]:
        outcome = await retrieval_service.retrieve(state.question, state.request_context)
        logger.info(
            "retrieval_completed organization_id=%s course_id=%s user_id=%s result_count=%d",
            state.request_context.organization_id,
            state.request_context.course_id,
            state.request_context.user_id,
            len(outcome.results),
        )
        return {
            "retrieval_results": outcome.results,
            "has_sufficient_evidence": outcome.has_sufficient_evidence,
        }

    async def evaluate_evidence(state: QueryGraphState) -> dict[str, object]:
        # has_sufficient_evidence was already decided by
        # RetrievalService.retrieve() in the `retrieve` node above (see
        # ADR-0002) — this node only observes and logs that decision.
        logger.info(
            "evidence_decision organization_id=%s course_id=%s user_id=%s "
            "has_sufficient_evidence=%s",
            state.request_context.organization_id,
            state.request_context.course_id,
            state.request_context.user_id,
            state.has_sufficient_evidence,
        )
        return {}

    def route_on_evidence(state: QueryGraphState) -> Literal["generate", "abstain"]:
        return "generate" if state.has_sufficient_evidence else "abstain"

    async def generate(state: QueryGraphState) -> dict[str, object]:
        # Always consumes `.stream()`, never `.generate()` directly — this
        # is what lets this one node implementation serve both invocation
        # modes: under `ainvoke()` the writer is a verified no-op (nobody
        # is listening for "custom" events), and under
        # `astream(stream_mode=["custom", ...])` each chunk is delivered
        # progressively as it arrives — see docs/architecture.md's PR-008
        # section for the empirical verification this relies on.
        writer = get_stream_writer()
        chunks: list[str] = []
        async for chunk in answer_generator_port.stream(state.question, state.retrieval_results):
            writer({"token": chunk})
            chunks.append(chunk)
        return {"answer": "".join(chunks)}

    async def build_citations(state: QueryGraphState) -> dict[str, object]:
        citations = [_to_citation(result) for result in state.retrieval_results]
        return {"citations": citations}

    async def abstain(state: QueryGraphState) -> dict[str, object]:
        # Pushes the fixed message word by word through the same writer
        # `generate` uses (a no-op under `ainvoke`, progressive `custom`
        # chunks under `astream`) — matching the word-by-word chunking
        # ExtractiveAnswerGeneratorAdapter.stream() uses for real content,
        # so local mode's observable SSE output for the insufficient-
        # evidence path is unchanged from before PR-008. This is the fixed
        # message itself, never the answer generator port.
        writer = get_stream_writer()
        words = NO_EVIDENCE_MESSAGE.split(" ")
        for index, word in enumerate(words):
            writer({"token": word if index == len(words) - 1 else f"{word} "})
        return {"answer": NO_EVIDENCE_MESSAGE, "citations": []}

    builder = StateGraph(QueryGraphState)
    builder.add_node("retrieve", retrieve)
    builder.add_node("evaluate_evidence", evaluate_evidence)
    builder.add_node("generate", generate)
    builder.add_node("build_citations", build_citations)
    builder.add_node("abstain", abstain)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "evaluate_evidence")
    builder.add_conditional_edges(
        "evaluate_evidence",
        route_on_evidence,
        {"generate": "generate", "abstain": "abstain"},
    )
    builder.add_edge("generate", "build_citations")
    builder.add_edge("build_citations", END)
    builder.add_edge("abstain", END)

    return builder.compile()


async def run_query_graph(graph: QueryGraph, initial_state: QueryGraphState) -> QueryGraphState:
    """Invoke the compiled graph and translate its result back into a typed
    ``QueryGraphState``. LangGraph's ``ainvoke`` returns ``dict[str, Any]``
    (its own typing, not ours, and a real library limitation — not
    something this module chose) — this is the one place that touches
    that, so callers outside this module (e.g. ``QueryService``) never
    need to.

    ``answer`` is cast back to its declared ``str | None`` here, not
    narrowed to ``str``: every graph path (``generate`` and ``abstain``)
    does set it before ``END``, but that is a topology guarantee, not
    something this function can verify from the raw dict alone.
    ``QueryService.answer()`` performs the actual non-None assertion,
    right before constructing ``QueryAnswer`` — that is the one place the
    ``str | None`` -> ``str`` narrowing actually happens.
    """
    result = await graph.ainvoke(initial_state)
    return _state_from_values(result)


def _state_from_values(values: dict[str, object]) -> QueryGraphState:
    return QueryGraphState(
        question=cast(str, values["question"]),
        request_context=cast(RequestContext, values["request_context"]),
        retrieval_results=cast("list[SearchResult]", values["retrieval_results"]),
        has_sufficient_evidence=cast(bool, values["has_sufficient_evidence"]),
        answer=cast("str | None", values["answer"]),
        citations=cast("list[Citation]", values["citations"]),
    )


@dataclass(frozen=True, slots=True)
class QueryStreamToken:
    """One progressively-delivered chunk of the answer, as pushed by the
    `generate` node's stream writer (see ``build_query_graph``)."""

    text: str


async def stream_query_graph(
    graph: QueryGraph, initial_state: QueryGraphState
) -> AsyncIterator[QueryStreamToken | QueryGraphState]:
    """Invoke the compiled graph progressively — the same graph, same
    nodes, same orchestration ``run_query_graph`` uses, just a different
    invocation method (``astream`` instead of ``ainvoke``). Yields a
    ``QueryStreamToken`` for every chunk pushed through the stream writer —
    both ``generate`` (real/extractive answer chunks) and ``abstain``
    (``NO_EVIDENCE_MESSAGE``, emitted progressively word by word, never
    through the answer generator port) call the writer, so a caller sees
    ``QueryStreamToken`` items on *either* path, not just the
    sufficient-evidence one. Finally yields the last ``QueryGraphState``
    snapshot once the graph reaches ``END`` — callers use that final state
    for ``citations``/``has_sufficient_evidence`` regardless of which path
    was taken (``citations`` is `[]` on the ``abstain`` path).

    Values events (``stream_mode="values"``) still report the *last*
    snapshot after every path — this is what makes the final
    ``QueryGraphState`` yielded here correct no matter which branch ran.

    A node exception (e.g. an AWS/Bedrock failure — see
    ``AnswerGenerationUnavailableError``) propagates out of this generator
    unwrapped, exactly like ``run_query_graph`` — see this module's
    docstring and docs/architecture.md's PR-008 section for what changes
    once ``routes.query_stream`` has already opened the SSE response by
    the time that happens.
    """
    final_values: dict[str, object] | None = None
    async for mode, chunk in graph.astream(initial_state, stream_mode=["custom", "values"]):
        if mode == "custom":
            yield QueryStreamToken(text=cast(str, cast(dict[str, object], chunk)["token"]))
        else:
            final_values = cast(dict[str, object], chunk)
    assert final_values is not None, "graph produced no final state"
    yield _state_from_values(final_values)
