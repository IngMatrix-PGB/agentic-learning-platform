"""PDF parsing via Docling, restricted to digital text (no OCR — out of scope
for this PR; scanned-only pages are rejected, not silently skipped).
"""

import asyncio
import io
import os

# Docling's layout model uses torch.compile() (dynamo/inductor) by default,
# which JIT-compiles C++ kernels for CPU inference — requiring a working
# g++/gcc. The `python:3.12-slim` runtime image deliberately has no compiler
# toolchain, so this fails there (observed empirically: "InvalidCxxCompiler"
# during a real container run) even though it silently succeeds on a
# developer machine that happens to have Xcode CLI tools / build-essential
# installed. Eager (non-compiled) inference doesn't need a compiler at all
# and is fast enough at this document-processing scale, so it is disabled
# unconditionally — not just in the container — for consistent behavior
# everywhere. Must be set before any torch-importing code runs.
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.io import DocumentStream

from agentic_learning_platform.application.ports.document_parser_port import (
    ExtractedDocument,
    ExtractedPage,
    IDocumentParserPort,
)
from agentic_learning_platform.exceptions import UnsupportedDocumentError


def _build_converter() -> DocumentConverter:
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False  # digital-text-only PDFs; OCR is out of scope.
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


class DoclingParserAdapter(IDocumentParserPort):
    """Loads the Docling model pipeline once and reuses it across calls —
    constructing a new ``DocumentConverter`` per request would reload models
    on every upload."""

    def __init__(self) -> None:
        self._converter: DocumentConverter | None = None

    def _get_converter(self) -> DocumentConverter:
        if self._converter is None:
            self._converter = _build_converter()
        return self._converter

    def _extract_sync(self, content: bytes, *, filename: str) -> ExtractedDocument:
        stream = DocumentStream(name=filename, stream=io.BytesIO(content))
        result = self._get_converter().convert(stream, raises_on_error=False)

        if result.document.num_pages() == 0:
            raise UnsupportedDocumentError(
                f"Could not extract any content from {filename!r}. Only PDFs with digital "
                "(non-scanned) text are supported in this version."
            )

        doc = result.document
        pages = [
            ExtractedPage(page_number=page_no, text=doc.export_to_text(page_no=page_no).strip())
            for page_no in range(1, doc.num_pages() + 1)
        ]

        if not any(page.text for page in pages):
            raise UnsupportedDocumentError(
                f"{filename!r} has no extractable digital text on any page (it may be a "
                "scanned/image-only PDF). OCR is not supported in this version."
            )

        return ExtractedDocument(pages=pages)

    async def extract(self, content: bytes, *, filename: str) -> ExtractedDocument:
        return await asyncio.to_thread(self._extract_sync, content, filename=filename)
