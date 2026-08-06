from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF

from agentic_learning_platform.app import create_app
from agentic_learning_platform.config import get_settings

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
    with TestClient(app) as test_client:
        yield test_client
