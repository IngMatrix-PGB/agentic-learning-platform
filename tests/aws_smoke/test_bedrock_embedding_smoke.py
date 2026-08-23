"""Opt-in (see conftest.py): validates the real Bedrock embedding adapter
against actual AWS Bedrock — dimension consistency and a real API call,
not a mocked response.
"""

from agentic_learning_platform.config import Settings
from agentic_learning_platform.infrastructure.embeddings.bedrock_embedding_adapter import (
    BedrockEmbeddingAdapter,
)


async def test_bedrock_embedding_returns_a_vector_of_the_configured_dimension(
    aws_smoke_settings: Settings,
) -> None:
    adapter = BedrockEmbeddingAdapter(aws_smoke_settings)

    vector = await adapter.embed_text("¿Qué es la gestión de incidentes?")

    assert len(vector) == aws_smoke_settings.embedding_dimension
    assert all(isinstance(value, float) for value in vector)
