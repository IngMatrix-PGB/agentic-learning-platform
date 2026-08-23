"""Application configuration.

A single, cached ``Settings`` object is the only source of runtime
configuration.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "agentic-learning-platform"
    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # --- Database (PostgreSQL + pgvector) ---
    # "localhost" is correct for running the app/tests directly on the host
    # against docker-compose's published port 5432. The `api` container
    # overrides this to "postgres" (the compose service name) explicitly in
    # docker-compose.yml, since "localhost" inside that container would not
    # reach the sibling `postgres` container.
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "agentic_learning"
    db_password: str = "agentic_learning"
    db_name: str = "agentic_learning"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 5

    # --- Execution mode ---
    # "local": FastEmbed (multilingual, in-process) + extractive answers.
    # "aws": AWS Bedrock embeddings + AWS Bedrock (ChatBedrockConverse).
    # Explicit and deterministic — never auto-detected from credentials.
    runtime_mode: Literal["local", "aws"] = "local"

    # Must match the vector column dimension of the database actually in use;
    # validated at startup against what was recorded when the schema was
    # migrated (see infrastructure.db.migrations.runner).
    embedding_dimension: int = 384

    # --- Local mode ---
    local_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # ".cache/fastembed" (relative to cwd) is correct for running the app/tests
    # directly on the host. The `api` container overrides this to the
    # absolute "/app/.cache/fastembed" explicitly in docker-compose.yml,
    # matching the fastembed_cache named volume mounted there.
    fastembed_cache_dir: str = ".cache/fastembed"

    # --- AWS mode ---
    aws_region: str = "us-east-1"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    bedrock_chat_model_id: str = "anthropic.claude-3-5-haiku-20241022-v1:0"
    bedrock_max_output_tokens: int = 1024
    bedrock_generation_timeout_seconds: int = 30
    # Bounded, SDK-level retries only (botocore's own "standard" retry mode)
    # — never a custom retry loop in application code or in a LangGraph node.
    bedrock_max_retries: int = 3
    # Required (validated at startup, not per-request) when runtime_mode is
    # "aws" — private bucket for source-document storage. See
    # infrastructure.storage.s3_document_storage_adapter.
    s3_bucket: str | None = None

    # --- Ingestion / retrieval ---
    max_upload_size_mb: int = 20
    chunk_max_chars: int = 1200
    retrieval_top_k: int = 5
    retrieval_score_threshold: float = 0.35

    # --- Query input limits ---
    # Shared by /v1/query and /v1/query/stream (see routes.query.QueryRequest)
    # — one contract, not two independently-drifting limits.
    max_question_length: int = 2000

    # --- Streaming (PR-003; real Bedrock streaming added in PR-008) ---
    # Local-mode-only UX pacing between SSE token events (ExtractiveAnswerGeneratorAdapter
    # has no real incremental generation latency of its own). Never applied to AWS-mode
    # chunks — real Bedrock token latency is the pacing there. See
    # routes.query_stream and docs/architecture.md's PR-008 section.
    stream_chunk_delay_ms: int = 40

    # --- CORS ---
    # Comma-separated, explicit origins — never "*". A plain str (not list[str])
    # keeps this consistent with pydantic-settings' env parsing for the rest of
    # this file (no JSON-in-env-var requirement for a single value).
    cors_allowed_origins: str = "http://localhost:8000"

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached ``Settings`` instance."""
    return Settings()


# Titan Embed Text V2's ``embeddingDimension`` request parameter only
# accepts these three values — not a benchmark choice, a hard constraint of
# the Bedrock API contract for this specific model.
_TITAN_EMBED_V2_VALID_DIMENSIONS = (256, 512, 1024)


class InvalidAwsConfigurationError(RuntimeError):
    """``runtime_mode="aws"`` is configured inconsistently.

    Deliberately not part of the ``AppError`` HTTP hierarchy (see
    exceptions.py): this must crash the process before it starts serving
    traffic, exactly like ``MigrationConflictError``, not be caught and
    turned into a per-request HTTP response.
    """


def validate_aws_configuration(settings: Settings) -> None:
    """Fail fast at startup — never per-request — if ``runtime_mode="aws"``
    would otherwise fail on the first real Bedrock/S3 call instead of at
    process startup."""
    if settings.runtime_mode != "aws":
        return
    if (
        settings.bedrock_embedding_model_id == "amazon.titan-embed-text-v2:0"
        and settings.embedding_dimension not in _TITAN_EMBED_V2_VALID_DIMENSIONS
    ):
        raise InvalidAwsConfigurationError(
            f"embedding_dimension={settings.embedding_dimension} is not valid for "
            f"{settings.bedrock_embedding_model_id!r}; Titan Embed Text V2 only supports "
            f"{_TITAN_EMBED_V2_VALID_DIMENSIONS}. Set EMBEDDING_DIMENSION to one of those "
            "values and migrate a fresh database for AWS mode — see docs/architecture.md."
        )
    if not settings.s3_bucket:
        raise InvalidAwsConfigurationError(
            'runtime_mode="aws" requires S3_BUCKET to be set (source-document storage).'
        )
