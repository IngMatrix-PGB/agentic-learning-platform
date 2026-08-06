"""Process entrypoint used by ``make run`` and the Docker image."""

import uvicorn

from agentic_learning_platform.app import create_app
from agentic_learning_platform.config import get_settings
from agentic_learning_platform.logging import build_uvicorn_log_config

app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "agentic_learning_platform.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_config=build_uvicorn_log_config(settings),
    )


if __name__ == "__main__":
    run()
