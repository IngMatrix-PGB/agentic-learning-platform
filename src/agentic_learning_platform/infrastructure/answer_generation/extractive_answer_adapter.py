"""Extractive local answer "generation" — returns the retrieved fragment(s)
verbatim. No LLM call happens here at all: this mode exists to demonstrate
parsing/chunking/embeddings/retrieval/citations, not answer quality (that is
validated with the AWS/Bedrock mode instead — see docs/architecture.md).

``stream`` yields the extractive text word by word (the same split
``routes.query_stream`` used to perform itself before PR-008) — not because
extractive mode has any real incremental generation, but so local-mode SSE
output keeps its existing word-by-word shape once the route delegates
chunking entirely to the port instead of doing it after the fact.
"""

from collections.abc import AsyncIterator

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.domain.models import SearchResult


def _extractive_text(evidence: list[SearchResult]) -> str:
    if not evidence:
        return ""
    if len(evidence) == 1:
        return evidence[0].content
    return "\n\n---\n\n".join(result.content for result in evidence)


class ExtractiveAnswerGeneratorAdapter(IAnswerGeneratorPort):
    async def stream(self, question: str, evidence: list[SearchResult]) -> AsyncIterator[str]:
        text = _extractive_text(evidence)
        if not text:
            return
        words = text.split(" ")
        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else f"{word} "
