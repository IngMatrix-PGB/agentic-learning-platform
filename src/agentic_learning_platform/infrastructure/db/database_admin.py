"""Cluster-level database administration (CREATE/DROP DATABASE) — distinct
from `pool.py`'s connection-pool lifecycle, since these operations run
against a connection to a *different* (admin) database than the one being
created or dropped.

Used only by the eval harness (`evals/runner.py`) to (re)create its own
dedicated database on every run — never by the application's own request
path or by `pytest` (see `tests/conftest.py`, which does the equivalent
inline for its own ephemeral database).
"""

import asyncpg


async def recreate_database(admin_dsn: str, database_name: str) -> None:
    """Drops `database_name` if it exists and creates it fresh. Connects via
    `admin_dsn` purely to issue cluster-level commands — never touches that
    database's own tables."""
    conn = await asyncpg.connect(dsn=admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await conn.close()
