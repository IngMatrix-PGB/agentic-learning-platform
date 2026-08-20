"""FastAPI application factory."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.application.services.query_service import QueryService
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.config import get_settings
from agentic_learning_platform.exceptions import register_exception_handlers
from agentic_learning_platform.infrastructure.db.migrations.runner import run_migrations
from agentic_learning_platform.infrastructure.db.pool import close_pool, create_pool
from agentic_learning_platform.infrastructure.di import (
    build_adapters,
    build_authorization_context_provider,
    build_lexical_search_port,
)
from agentic_learning_platform.logging import configure_logging
from agentic_learning_platform.routes import (
    documents_router,
    health_router,
    query_router,
    query_stream_router,
)

# Relative to the current working directory, not to this module's own file:
# `uv sync --no-editable` (used in the Docker image, see Dockerfile) installs
# this package into `.venv/lib/.../site-packages/`, so `__file__`-relative
# parents no longer point at the repo root there. `pytest`/`make run` are
# invoked from the repo root, and the container's WORKDIR is `/app` with
# `web/` copied alongside `src/` — "web" resolves correctly against the cwd
# in both cases (the same reasoning as `fastembed_cache_dir` in config.py).
_WEB_DIR = Path("web")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()

    # Runs against a standalone connection (not the pool below) — the pool's
    # pgvector codec registration requires the `vector` extension to already
    # exist. This call is also where the "declared vs. configured dimension"
    # startup check happens: re-rendering an already-applied migration with a
    # different embedding_dimension raises immediately (see
    # infrastructure.db.migrations.runner.run_migrations).
    await run_migrations(settings)

    pool = await create_pool(settings)
    app.state.db_pool = pool

    adapters = build_adapters(settings, pool)
    lexical_search_port = build_lexical_search_port(settings, pool)
    retrieval_service = RetrievalService(
        adapters.embedding,
        adapters.vector_store,
        top_k=settings.retrieval_top_k,
        score_threshold=settings.retrieval_score_threshold,
        lexical_search_port=lexical_search_port,
        candidate_top_k=settings.hybrid_candidate_top_k,
        rrf_k=settings.hybrid_rrf_k,
    )
    app.state.ingestion_service = IngestionService(
        adapters.parser,
        adapters.embedding,
        adapters.vector_store,
        max_upload_size_mb=settings.max_upload_size_mb,
        chunk_max_chars=settings.chunk_max_chars,
    )
    app.state.query_service = QueryService(retrieval_service, adapters.answer_generator)
    app.state.authorization_context_provider = build_authorization_context_provider(settings)

    logger.info(
        "startup_config runtime_mode=%s retrieval_strategy=%s embedding_model=%s "
        "embedding_dimension=%d",
        settings.runtime_mode,
        settings.retrieval_strategy,
        adapters.embedding.get_model_name(),
        adapters.embedding.get_dimension(),
    )

    yield

    await close_pool(pool)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
        lifespan=_lifespan,
    )

    # Explicit, configurable origins — never "*" (see docs/architecture.md).
    # The /demo page is served by this same app, so it never needs CORS at
    # all; this exists for the widget being embedded on a *different* origin
    # (a real client portal, in a later PR).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_methods=["GET", "POST"],
        # X-Organization-Id/X-Course-Id/X-User-Id: the PR-004 dev-only
        # authorization context headers (see routes.authorization) — a
        # cross-origin widget needs these listed here or the browser's CORS
        # preflight rejects them before the request is ever sent.
        allow_headers=["Content-Type", "X-Organization-Id", "X-Course-Id", "X-User-Id"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(query_router)
    app.include_router(query_stream_router)

    app.mount("/demo", StaticFiles(directory=_WEB_DIR / "demo", html=True), name="demo")
    app.mount("/widget", StaticFiles(directory=_WEB_DIR / "widget"), name="widget")

    return app
