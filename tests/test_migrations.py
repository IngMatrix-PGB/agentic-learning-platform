"""Tests for the deterministic, versioned migration runner (against a real
Postgres — pgvector's schema behavior is the thing being validated, so it is
not mocked)."""

import asyncpg
import pytest

from agentic_learning_platform.config import Settings, get_settings
from agentic_learning_platform.infrastructure.db.migrations.runner import (
    MigrationConflictError,
    run_migrations,
)


@pytest.fixture
def settings() -> Settings:
    return get_settings()


async def test_migrations_are_idempotent(settings: Settings) -> None:
    await run_migrations(settings)
    await run_migrations(settings)  # must not raise, and must not re-apply


async def test_migrations_reject_a_different_dimension_for_the_same_version(
    settings: Settings,
) -> None:
    await run_migrations(settings)  # ensure applied with the real configured dimension

    conflicting = settings.model_copy(
        update={"embedding_dimension": settings.embedding_dimension + 1}
    )

    with pytest.raises(MigrationConflictError):
        await run_migrations(conflicting)


async def test_schema_migrations_records_the_applied_dimension(settings: Settings) -> None:
    await run_migrations(settings)

    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT embedding_dimension, checksum FROM schema_migrations WHERE version = $1",
            "001_init_rag_schema",
        )
    finally:
        await conn.close()

    assert row is not None
    assert row["embedding_dimension"] == settings.embedding_dimension
    assert row["checksum"]
