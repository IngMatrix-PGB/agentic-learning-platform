"""FastAPI application factory."""

from fastapi import FastAPI

from agentic_learning_platform.config import get_settings
from agentic_learning_platform.exceptions import register_exception_handlers
from agentic_learning_platform.logging import configure_logging
from agentic_learning_platform.routes import health_router


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    No ``lifespan`` context manager yet: there is no resource (database pool,
    connection, ...) to open or close in this PR. It is added in the PR that
    introduces the first such resource.
    """
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
    )

    register_exception_handlers(app)
    app.include_router(health_router)

    return app
