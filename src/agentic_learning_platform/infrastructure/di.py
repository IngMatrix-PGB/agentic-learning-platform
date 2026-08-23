"""Adapter selection by ``settings.runtime_mode`` — explicit and
deterministic, never auto-detected from credentials.

Plain factory functions, not a DI container library: with only five ports
and two modes, a container would be pure ceremony (see docs/architecture.md).
"""

from dataclasses import dataclass

import asyncpg

from agentic_learning_platform.application.ports.answer_generator_port import IAnswerGeneratorPort
from agentic_learning_platform.application.ports.authorization_context_port import (
    IAuthorizationContextProvider,
)
from agentic_learning_platform.application.ports.document_parser_port import IDocumentParserPort
from agentic_learning_platform.application.ports.document_storage_port import IDocumentStoragePort
from agentic_learning_platform.application.ports.embedding_port import IEmbeddingPort
from agentic_learning_platform.application.ports.vector_store_port import IVectorStorePort
from agentic_learning_platform.config import Settings, validate_aws_configuration
from agentic_learning_platform.infrastructure.answer_generation.bedrock_answer_adapter import (
    BedrockAnswerGeneratorAdapter,
)
from agentic_learning_platform.infrastructure.answer_generation.extractive_answer_adapter import (
    ExtractiveAnswerGeneratorAdapter,
)
from agentic_learning_platform.infrastructure.authorization.dev_header_provider import (
    DevHeaderAuthorizationContextProvider,
)
from agentic_learning_platform.infrastructure.embeddings.bedrock_embedding_adapter import (
    BedrockEmbeddingAdapter,
)
from agentic_learning_platform.infrastructure.embeddings.local_embedding_adapter import (
    LocalEmbeddingAdapter,
)
from agentic_learning_platform.infrastructure.parsers.docling_parser_adapter import (
    DoclingParserAdapter,
)
from agentic_learning_platform.infrastructure.storage.null_document_storage_adapter import (
    NullDocumentStorageAdapter,
)
from agentic_learning_platform.infrastructure.storage.s3_document_storage_adapter import (
    S3DocumentStorageAdapter,
)
from agentic_learning_platform.infrastructure.vector_store.pgvector_vector_store_adapter import (
    PgVectorStoreAdapter,
)


@dataclass(frozen=True, slots=True)
class Adapters:
    parser: IDocumentParserPort
    embedding: IEmbeddingPort
    vector_store: IVectorStorePort
    answer_generator: IAnswerGeneratorPort
    document_storage: IDocumentStoragePort


def build_adapters(settings: Settings, pool: asyncpg.Pool) -> Adapters:
    """Build the one consistent set of adapters for ``settings.runtime_mode``
    — never a mixed combination. Validates AWS configuration (embedding
    dimension, S3 bucket) at startup, before constructing any AWS client —
    never per request."""
    parser = DoclingParserAdapter()
    vector_store = PgVectorStoreAdapter(pool)

    if settings.runtime_mode == "aws":
        validate_aws_configuration(settings)
        return Adapters(
            parser=parser,
            embedding=BedrockEmbeddingAdapter(settings),
            vector_store=vector_store,
            answer_generator=BedrockAnswerGeneratorAdapter(settings),
            document_storage=S3DocumentStorageAdapter(settings),
        )

    return Adapters(
        parser=parser,
        embedding=LocalEmbeddingAdapter(settings),
        vector_store=vector_store,
        answer_generator=ExtractiveAnswerGeneratorAdapter(),
        document_storage=NullDocumentStorageAdapter(),
    )


def build_authorization_context_provider(settings: Settings) -> IAuthorizationContextProvider:
    """Only one implementation exists today (dev headers) — ``settings`` is
    accepted for the same reason ``build_adapters`` takes it: this is the
    seam a future PR replaces with a real JWT/OIDC-backed provider, without
    touching QueryService/IngestionService or any route."""
    return DevHeaderAuthorizationContextProvider()
