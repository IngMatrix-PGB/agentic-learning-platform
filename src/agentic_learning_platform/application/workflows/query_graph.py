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
from dataclasses import dataclass, field
from typing import Literal, cast

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
        answer_text = await answer_generator_port.generate(state.question, state.retrieval_results)
        return {"answer": answer_text}

    async def build_citations(state: QueryGraphState) -> dict[str, object]:
        citations = [_to_citation(result) for result in state.retrieval_results]
        return {"citations": citations}

    async def abstain(state: QueryGraphState) -> dict[str, object]:
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
    return QueryGraphState(
        question=cast(str, result["question"]),
        request_context=cast(RequestContext, result["request_context"]),
        retrieval_results=cast("list[SearchResult]", result["retrieval_results"]),
        has_sufficient_evidence=cast(bool, result["has_sufficient_evidence"]),
        answer=cast("str | None", result["answer"]),
        citations=cast("list[Citation]", result["citations"]),
    )
