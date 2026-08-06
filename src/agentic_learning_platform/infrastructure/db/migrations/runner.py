"""Deterministic, versioned SQL migration runner.

No Alembic: migrations are plain, explicit ``.sql`` files under ``sql/``,
with exactly one controlled substitution (``{{EMBEDDING_DIMENSION}}``) —
everything else in each file is literal SQL, as required.

Every application startup calls :func:`run_migrations`, which re-renders
every migration file with the *current* ``settings.embedding_dimension`` and
compares the result against what is recorded in ``schema_migrations`` for
that version. This is also how the "declared dimension vs. configured
dimension" check at startup is satisfied: rendering a migration that was
already applied with a different dimension raises immediately, rather than
silently reapplying or ignoring the mismatch — the app never starts against a
database whose schema doesn't match its own configuration.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import asyncpg

from agentic_learning_platform.config import Settings

MIGRATIONS_DIR = Path(__file__).parent / "sql"


class MigrationConflictError(RuntimeError):
    """A migration version was already applied with a different rendered
    checksum or embedding dimension than the one being applied now.

    Deliberately not part of the ``AppError`` HTTP hierarchy: this must crash
    the process before it starts serving traffic.
    """


async def _ensure_bookkeeping_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def _render(sql_template: str, *, embedding_dimension: int) -> str:
    return sql_template.replace("{{EMBEDDING_DIMENSION}}", str(embedding_dimension))


def _checksum(rendered_sql: str) -> str:
    return hashlib.sha256(rendered_sql.encode()).hexdigest()


async def run_migrations(settings: Settings) -> None:
    """Apply every ``sql/*.sql`` migration, in filename order, against a
    standalone connection (not the app's pool — the pool's pgvector codec
    registration requires the ``vector`` extension to already exist)."""
    conn = await asyncpg.connect(dsn=settings.database_dsn)
    try:
        await _ensure_bookkeeping_table(conn)

        for sql_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = sql_path.stem
            rendered = _render(
                sql_path.read_text(), embedding_dimension=settings.embedding_dimension
            )
            checksum = _checksum(rendered)

            existing = await conn.fetchrow(
                "SELECT checksum, embedding_dimension FROM schema_migrations WHERE version = $1",
                version,
            )

            if existing is None:
                async with conn.transaction():
                    await conn.execute(rendered)
                    await conn.execute(
                        """
                        INSERT INTO schema_migrations
                            (version, checksum, embedding_dimension, applied_at)
                        VALUES ($1, $2, $3, $4)
                        """,
                        version,
                        checksum,
                        settings.embedding_dimension,
                        datetime.now(UTC),
                    )
                continue

            if existing["embedding_dimension"] != settings.embedding_dimension:
                raise MigrationConflictError(
                    f"Migration {version!r} was already applied with "
                    f"embedding_dimension={existing['embedding_dimension']}, but the current "
                    f"configuration requests embedding_dimension={settings.embedding_dimension}. "
                    "Changing the embedding dimension against an existing database requires a "
                    "new migration and a re-embed of existing data, not re-running this one — "
                    "switching runtime_mode against this database is refused for the same reason."
                )

            if existing["checksum"] != checksum:
                raise MigrationConflictError(
                    f"Migration {version!r} was already applied with a different rendered SQL "
                    "checksum (the .sql file changed after being applied). Refusing to silently "
                    "re-run it — add a new migration instead of editing an applied one."
                )
            # Same version, same dimension, same checksum: already applied, no-op.
    finally:
        await conn.close()
