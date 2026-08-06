"""Port for extracting page-level text from a source document."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    pages: list[ExtractedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)


class IDocumentParserPort(ABC):
    """Extracts page-level text from a document's raw bytes.

    Implementations may run CPU-bound parsing internally (e.g. via
    ``asyncio.to_thread``) — callers only see the async contract.
    """

    @abstractmethod
    async def extract(self, content: bytes, *, filename: str) -> ExtractedDocument: ...
