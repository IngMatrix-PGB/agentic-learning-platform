"""Extractive local answer "generation" — returns the retrieved fragment(s)
verbatim. No LLM call happens here at all: this mode exists to demonstrate
parsing/chunking/embeddings/retrieval/citations, not answer quality (that is
validated with the AWS/Bedrock mode instead — see docs/architecture.md).
"""

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.domain.models import SearchResult


class ExtractiveAnswerGeneratorAdapter(IAnswerGeneratorPort):
    async def generate(self, question: str, evidence: list[SearchResult]) -> str:
        if not evidence:
            return ""
        if len(evidence) == 1:
            return evidence[0].content
        return "\n\n---\n\n".join(result.content for result in evidence)
