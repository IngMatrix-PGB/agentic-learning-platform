"""Deterministic page-based chunking with length subdivision.

Not a port: chunking has no alternate implementation to swap in this PR, so
an interface here would be speculative (see docs/architecture.md — ports
exist only for embeddings, vector store, parser and answer generator).
"""

from dataclasses import dataclass

from agentic_learning_platform.application.ports.document_parser_port import ExtractedDocument


@dataclass(frozen=True, slots=True)
class PendingChunk:
    page_number: int
    chunk_index: int
    content: str


def chunk_by_page(document: ExtractedDocument, *, max_chars: int) -> list[PendingChunk]:
    """One chunk per page, unless a page's text exceeds ``max_chars`` — then
    it is split into consecutive, non-overlapping slices at whitespace
    boundaries where possible.

    ``chunk_index`` is a single sequence across the whole document (not
    reset per page), so it is directly usable as a stable ordering key.
    """
    chunks: list[PendingChunk] = []
    chunk_index = 0

    for page in document.pages:
        if not page.text:
            continue

        for piece in _split_by_length(page.text, max_chars=max_chars):
            chunks.append(
                PendingChunk(page_number=page.page_number, chunk_index=chunk_index, content=piece)
            )
            chunk_index += 1

    return chunks


def _split_by_length(text: str, *, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            pieces.append(remaining.strip())
            break

        split_at = remaining.rfind(" ", 0, max_chars)
        if split_at <= 0:
            split_at = max_chars

        pieces.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    return [piece for piece in pieces if piece]
