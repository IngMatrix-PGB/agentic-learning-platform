"""FastAPI application factory."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentic_learning_platform.application.services.ingestion_service import IngestionService
from agentic_learning_platform.application.services.query_service import QueryService
from agentic_learning_platform.application.services.retrieval_service import RetrievalService
from agentic_learning_platform.config import get_settings
from agentic_learning_platform.exceptions import register_exception_handlers
from agentic_learning_platform.infrastructure.db.migrations.runner import run_migrations
from agentic_learning_platform.infrastructure.db.pool import close_pool, create_pool
from agentic_learning_platform.infrastructure.di import build_adapters
from agentic_learning_platform.logging import configure_logging
from agentic_learning_platform.routes import documents_router, health_router, query_router

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
    retrieval_service = RetrievalService(
        adapters.embedding,
        adapters.vector_store,
        top_k=settings.retrieval_top_k,
        score_threshold=settings.retrieval_score_threshold,
    )
    app.state.ingestion_service = IngestionService(
        adapters.parser,
        adapters.embedding,
        adapters.vector_store,
        max_upload_size_mb=settings.max_upload_size_mb,
        chunk_max_chars=settings.chunk_max_chars,
    )
    app.state.query_service = QueryService(retrieval_service, adapters.answer_generator)

    logger.info(
        "startup_config runtime_mode=%s embedding_model=%s embedding_dimension=%d",
        settings.runtime_mode,
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

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(documents_router)
    app.include_router(query_router)

    return app
