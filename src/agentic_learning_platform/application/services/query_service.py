"""Orchestrates the full question-answering flow: retrieve, short-circuit on
insufficient evidence (never calling the answer generator in that case),
otherwise generate and attach citations.
"""

import logging

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.domain.models import (
    Citation,
    QueryAnswer,
    RequestContext,
    SearchResult,
)

NO_EVIDENCE_MESSAGE = "No hay información suficiente en el contenido disponible."

logger = logging.getLogger(__name__)


class QueryService:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        answer_generator_port: IAnswerGeneratorPort,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._answer_generator_port = answer_generator_port

    async def answer(self, question: str, context: RequestContext) -> QueryAnswer:
        outcome = await self._retrieval_service.retrieve(question, context)

        if not outcome.has_sufficient_evidence:
            logger.info(
                "query_answered organization_id=%s course_id=%s user_id=%s "
                "has_sufficient_evidence=False citations=0",
                context.organization_id,
                context.course_id,
                context.user_id,
            )
            return QueryAnswer(
                answer=NO_EVIDENCE_MESSAGE, citations=[], has_sufficient_evidence=False
            )

        answer_text = await self._answer_generator_port.generate(question, outcome.results)
        citations = [_to_citation(result) for result in outcome.results]
        logger.info(
            "query_answered organization_id=%s course_id=%s user_id=%s "
            "has_sufficient_evidence=True citations=%d",
            context.organization_id,
            context.course_id,
            context.user_id,
            len(citations),
        )
        return QueryAnswer(answer=answer_text, citations=citations, has_sufficient_evidence=True)


def _to_citation(result: SearchResult) -> Citation:
    return Citation(
        source=result.source_name,
        page=result.page_number,
        chunk_id=result.chunk_id,
        score=result.score,
    )
