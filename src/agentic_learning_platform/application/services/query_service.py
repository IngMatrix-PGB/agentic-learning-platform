"""Thin facade over the LangGraph query workflow (PR-007).

All retrieval/evidence/generation/citation logic lives in
``application.workflows.query_graph`` — this class only builds the initial
graph state, awaits the compiled graph, and translates its final state back
into the existing ``QueryAnswer`` domain type. There is exactly one
orchestration path; this is not a second implementation of it.
"""

import logging

from agentic_learning_platform.application.workflows.query_graph import (
    NO_EVIDENCE_MESSAGE as NO_EVIDENCE_MESSAGE,
)
from agentic_learning_platform.application.workflows.query_graph import (
    QueryGraph,
    QueryGraphState,
    run_query_graph,
)
from agentic_learning_platform.domain.models import QueryAnswer, RequestContext

logger = logging.getLogger(__name__)


class QueryService:
    def __init__(self, graph: QueryGraph) -> None:
        self._graph = graph

    async def answer(self, question: str, context: RequestContext) -> QueryAnswer:
        logger.info(
            "workflow_started organization_id=%s course_id=%s user_id=%s",
            context.organization_id,
            context.course_id,
            context.user_id,
        )

        initial_state = QueryGraphState(question=question, request_context=context)
        final_state = await run_query_graph(self._graph, initial_state)
        # `final_state.answer` is `str | None` because `run_query_graph`
        # deliberately does not narrow it (see that function's docstring —
        # LangGraph's `ainvoke` returns an untyped mapping, and answer's
        # non-None-ness is a topology guarantee, not something derivable
        # from the raw dict). This assert is the one place that guarantee
        # is actually checked, right before constructing `QueryAnswer`
        # (whose `answer` field is `str`, not `str | None`).
        assert final_state.answer is not None, "query graph did not set an answer"

        logger.info(
            "workflow_completed organization_id=%s course_id=%s user_id=%s "
            "has_sufficient_evidence=%s citations=%d",
            context.organization_id,
            context.course_id,
            context.user_id,
            final_state.has_sufficient_evidence,
            len(final_state.citations),
        )
        return QueryAnswer(
            answer=final_state.answer,
            citations=final_state.citations,
            has_sufficient_evidence=final_state.has_sufficient_evidence,
        )
