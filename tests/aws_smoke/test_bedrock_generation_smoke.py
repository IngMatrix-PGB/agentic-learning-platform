"""Opt-in (see conftest.py): validates real Bedrock generation, both
buffered (``generate``) and — critically — real progressive streaming
(``stream``). The streaming assertion is the one thing this suite exists
to prove: it must observe more than one chunk arriving over time, not a
single buffered block dressed up as a stream (see docs/architecture.md's
PR-008 section on why this test does not mock the streaming protocol).
"""

import uuid

from agentic_learning_platform.config import Settings
from agentic_learning_platform.domain.models import SearchResult
from agentic_learning_platform.infrastructure.answer_generation.bedrock_answer_adapter import (
    BedrockAnswerGeneratorAdapter,
)

_EVIDENCE = [
    SearchResult(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        source_name="itsm_glossary.pdf",
        page_number=1,
        chunk_index=0,
        content=(
            "Gestion de Incidentes: El objetivo de la gestion de incidentes es "
            "restaurar el servicio interrumpido lo mas rapido posible."
        ),
        score=0.9,
    )
]


async def test_bedrock_generate_returns_a_non_empty_answer(
    aws_smoke_settings: Settings,
) -> None:
    adapter = BedrockAnswerGeneratorAdapter(aws_smoke_settings)

    answer = await adapter.generate("¿Qué es la gestión de incidentes?", _EVIDENCE)

    assert answer.strip() != ""


async def test_bedrock_stream_delivers_multiple_progressive_chunks(
    aws_smoke_settings: Settings,
) -> None:
    adapter = BedrockAnswerGeneratorAdapter(aws_smoke_settings)

    chunks = [
        chunk async for chunk in adapter.stream("¿Qué es la gestión de incidentes?", _EVIDENCE)
    ]

    # The real assertion: genuine token streaming arrives as more than one
    # chunk. A single buffered chunk here would mean this is not actually
    # streaming, regardless of what the code claims.
    assert len(chunks) > 1
    assert "".join(chunks).strip() != ""
