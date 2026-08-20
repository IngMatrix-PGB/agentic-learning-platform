"""Port for turning retrieved evidence into an answer.

Never called when evidence is insufficient — that short-circuit lives in
``application.services.query_service``, not in any implementation of this
port.
"""

from abc import ABC, abstractmethod

from agentic_learning_platform.domain.models import SearchResult


class IAnswerGeneratorPort(ABC):
    @abstractmethod
    async def generate(self, question: str, evidence: list[SearchResult]) -> str: ...
