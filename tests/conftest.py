from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from agentic_learning_platform.app import create_app
from agentic_learning_platform.config import get_settings


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
