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

    # --- Ingestion / retrieval ---
    max_upload_size_mb: int = 20
    chunk_max_chars: int = 1200
    retrieval_top_k: int = 5
    retrieval_score_threshold: float = 0.35

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached ``Settings`` instance."""
    return Settings()
