"""Port for turning retrieved evidence into an answer.

Never called when evidence is insufficient — that short-circuit lives in
``application.workflows.query_graph``, not in any implementation of this
port.

``stream`` is the single generation primitive every adapter implements.
``generate`` is a concrete method derived from it (accumulate every chunk),
not a second, independently-implemented generation path — this is what lets
the query graph's ``generate`` node consume the exact same adapter behavior
whether the graph is invoked via ``ainvoke`` (buffered) or ``astream``
(progressive) — see docs/architecture.md's PR-008 section.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from agentic_learning_platform.domain.models import SearchResult


class IAnswerGeneratorPort(ABC):
    @abstractmethod
    def stream(self, question: str, evidence: list[SearchResult]) -> AsyncIterator[str]:
        """Yield the answer progressively, chunk by chunk. Implementations
        that have no real incremental generation (e.g. extractive mode) may
        yield the whole answer as a single chunk — callers must not assume
        more than one chunk will ever arrive."""
        ...

    async def generate(self, question: str, evidence: list[SearchResult]) -> str:
        """Buffered convenience built on ``stream`` — never overridden by
        adapters, so there is exactly one generation implementation per
        adapter, not two."""
        return "".join([chunk async for chunk in self.stream(question, evidence)])
