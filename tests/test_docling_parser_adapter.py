"""Tests for the Docling PDF parser adapter, using synthetic PDFs (no OCR,
digital text only — per PR-002 scope)."""

import pytest

from agentic_learning_platform.exceptions import UnsupportedDocumentError
from agentic_learning_platform.infrastructure.parsers.docling_parser_adapter import (
    DoclingParserAdapter,
)


async def test_extracts_text_per_page_with_correct_page_numbers(sample_pdf_bytes: bytes) -> None:
    adapter = DoclingParserAdapter()

    result = await adapter.extract(sample_pdf_bytes, filename="manual.pdf")

    assert result.page_count == 2
    assert result.pages[0].page_number == 1
    assert "incidentes" in result.pages[0].text.lower()
    assert result.pages[1].page_number == 2
    assert "problemas" in result.pages[1].text.lower()


async def test_rejects_a_pdf_with_no_extractable_text(blank_pdf_bytes: bytes) -> None:
    adapter = DoclingParserAdapter()

    with pytest.raises(UnsupportedDocumentError):
        await adapter.extract(blank_pdf_bytes, filename="blank.pdf")
