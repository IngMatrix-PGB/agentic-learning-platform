"""Thin facade over the LangGraph query workflow (PR-007/PR-008).

All retrieval/evidence/generation/citation logic lives in
``application.workflows.query_graph`` — this class only builds the initial
graph state and invokes the compiled graph, either buffered (``answer``,
via ``ainvoke``) or progressively (``answer_stream``, via ``astream``).
Both methods drive the exact same graph and nodes — there is exactly one
orchestration path, not two; only the invocation/delivery mechanism
differs. See docs/architecture.md's PR-008 section.
"""

import logging
from collections.abc import AsyncIterator

from agentic_learning_platform.application.workflows.query_graph import (
    NO_EVIDENCE_MESSAGE as NO_EVIDENCE_MESSAGE,
)
from agentic_learning_platform.application.workflows.query_graph import (
    QueryGraph,
    QueryGraphState,
    QueryStreamToken,
    run_query_graph,
    stream_query_graph,
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

        self._log_workflow_completed(context, final_state)
        return QueryAnswer(
            answer=final_state.answer,
            citations=final_state.citations,
            has_sufficient_evidence=final_state.has_sufficient_evidence,
        )

    async def answer_stream(
        self, question: str, context: RequestContext
    ) -> AsyncIterator[QueryStreamToken | QueryAnswer]:
        """Progressive counterpart to ``answer`` — same graph, same nodes
        (see ``stream_query_graph``). Yields a ``QueryStreamToken`` per
        chunk as the ``generate`` node's writer pushes them, then a final
        ``QueryAnswer`` once the graph reaches ``END``. A node exception
        (e.g. a Bedrock failure) propagates unwrapped, possibly after some
        tokens were already yielded — see routes.query_stream for how that
        surfaces as an SSE ``event: error`` once the stream has started."""
        logger.info(
            "workflow_started organization_id=%s course_id=%s user_id=%s",
            context.organization_id,
            context.course_id,
            context.user_id,
        )

        initial_state = QueryGraphState(question=question, request_context=context)
        async for item in stream_query_graph(self._graph, initial_state):
            if isinstance(item, QueryStreamToken):
                yield item
                continue

            final_state = item
            assert final_state.answer is not None, "query graph did not set an answer"
            self._log_workflow_completed(context, final_state)
            yield QueryAnswer(
                answer=final_state.answer,
                citations=final_state.citations,
                has_sufficient_evidence=final_state.has_sufficient_evidence,
            )

    def _log_workflow_completed(
        self, context: RequestContext, final_state: QueryGraphState
    ) -> None:
        logger.info(
            "workflow_completed organization_id=%s course_id=%s user_id=%s "
            "has_sufficient_evidence=%s citations=%d",
            context.organization_id,
            context.course_id,
            context.user_id,
            final_state.has_sufficient_evidence,
            len(final_state.citations),
        )
