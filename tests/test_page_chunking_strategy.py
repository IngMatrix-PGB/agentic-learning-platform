"""Tests for the deterministic page-based chunking strategy (pure function,
no I/O)."""

from agentic_learning_platform.application.ports.document_parser_port import (
    ExtractedDocument,
    ExtractedPage,
)
from agentic_learning_platform.infrastructure.chunking.page_chunking_strategy import chunk_by_page


def test_short_page_produces_exactly_one_chunk() -> None:
    document = ExtractedDocument(pages=[ExtractedPage(page_number=1, text="Texto corto.")])

    chunks = chunk_by_page(document, max_chars=1200)

    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == "Texto corto."


def test_long_page_is_subdivided_within_the_character_limit() -> None:
    long_text = "palabra " * 500
    document = ExtractedDocument(pages=[ExtractedPage(page_number=1, text=long_text)])

    chunks = chunk_by_page(document, max_chars=200)

    assert len(chunks) > 1
    assert all(chunk.page_number == 1 for chunk in chunks)
    assert all(len(chunk.content) <= 200 for chunk in chunks)


def test_chunk_index_is_sequential_across_the_whole_document() -> None:
    document = ExtractedDocument(
        pages=[
            ExtractedPage(page_number=1, text="Pagina uno."),
            ExtractedPage(page_number=2, text="Pagina dos."),
        ]
    )

    chunks = chunk_by_page(document, max_chars=1200)

    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert [chunk.page_number for chunk in chunks] == [1, 2]


def test_empty_page_produces_no_chunks() -> None:
    document = ExtractedDocument(pages=[ExtractedPage(page_number=1, text="")])

    chunks = chunk_by_page(document, max_chars=1200)

    assert chunks == []
