import asyncio
import os
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from agentic_learning_platform.app import create_app
from agentic_learning_platform.config import get_settings

# DEV ONLY: a trusted local development context (PR-004), not real
# authentication — see docs/architecture.md. Set as the `client` fixture's
# default headers so every existing test keeps working unmodified; a test
# that specifically needs a different (or missing) scope overrides these
# per-request (httpx merges per-request headers over client defaults).
DEFAULT_TEST_ORGANIZATION_ID = "org-test-default"
DEFAULT_TEST_COURSE_ID = "course-test-default"
DEFAULT_TEST_USER_ID = "user-test-default"
_DEFAULT_CONTEXT_HEADERS = {
    "X-Organization-Id": DEFAULT_TEST_ORGANIZATION_ID,
    "X-Course-Id": DEFAULT_TEST_COURSE_ID,
    "X-User-Id": DEFAULT_TEST_USER_ID,
}

PAGE_ONE_TEXT = (
    "Gestion de Incidentes: El objetivo de la gestion de incidentes es restaurar "
    "el servicio interrumpido lo mas rapido posible, minimizando el impacto en el negocio."
)
PAGE_TWO_TEXT = (
    "Gestion de Problemas: La gestion de problemas busca identificar la causa raiz "
    "de los incidentes recurrentes para prevenir que vuelvan a ocurrir."
)


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    """A small, deterministic 2-page PDF with known, distinguishable content
    per page — generated at test time (no fixture file), so there is no
    licensing question about a real-world sample document.
    """
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    pdf.add_page()
    pdf.multi_cell(0, 10, PAGE_ONE_TEXT)
    pdf.add_page()
    pdf.multi_cell(0, 10, PAGE_TWO_TEXT)
    return bytes(pdf.output())


@pytest.fixture(scope="session")
def blank_pdf_bytes() -> bytes:
    """A syntactically valid PDF with no text content at all."""
    pdf = FPDF()
    pdf.add_page()
    return bytes(pdf.output())


# Pytest discovers and invokes autouse fixtures by name via its plugin
# machinery, not through a direct call anywhere in this module, so pyright
# has no way to see this as "used" — a known false positive for pytest
# fixtures, not dead code.
@pytest.fixture(scope="session", autouse=True)
def _isolated_test_database() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Tests get their own ephemeral Postgres database on the same server
    used for local dev/demo — created once per test session and dropped at
    the end — so `pytest` no longer shares a corpus with `docker compose up`
    manual demo usage (see docs/architecture.md's PR-004 section; this
    replaces the earlier `docker compose down -v` manual workaround for
    tests specifically — the demo's own database is untouched by this).

    Runs as plain sync code with its own throwaway `asyncio.run()` calls:
    this fixture executes once per session, well outside any per-test event
    loop pytest-asyncio manages for the `async def` test functions.
    """
    admin_dsn = get_settings().database_dsn
    db_name = f"pytest_{uuid.uuid4().hex[:12]}"

    async def _create_database() -> None:
        conn = await asyncpg.connect(dsn=admin_dsn)
        try:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await conn.close()

    async def _drop_database() -> None:
        conn = await asyncpg.connect(dsn=admin_dsn)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        finally:
            await conn.close()

    asyncio.run(_create_database())
    os.environ["DB_NAME"] = db_name
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()
        asyncio.run(_drop_database())
        del os.environ["DB_NAME"]


# Pytest discovers and invokes autouse fixtures by name via its plugin
# machinery, not through a direct call anywhere in this module, so pyright
# has no way to see this as "used" — a known false positive for pytest
# fixtures, not dead code.
@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """`get_settings()` is cached process-wide via `lru_cache`. Clear it
    before and after every test so no test can leak a `Settings` instance
    built from whatever env vars/`.env` happened to be present at the time
    into another test.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, headers=_DEFAULT_CONTEXT_HEADERS) as test_client:
        yield test_client
