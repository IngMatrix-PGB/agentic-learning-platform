"""Async PostgreSQL connection pool, with pgvector's `vector` codec
registered on every connection so asyncpg can bind/read Python lists as
pgvector vectors directly.
"""

import asyncpg
from pgvector.asyncpg import register_vector

from agentic_learning_platform.config import Settings


async def create_pool(settings: Settings) -> asyncpg.Pool:
    async def _init_connection(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    return await asyncpg.create_pool(
        dsn=settings.database_dsn,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        init=_init_connection,
    )


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()
