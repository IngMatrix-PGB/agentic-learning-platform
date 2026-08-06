"""Application-wide exception handling.

A single, flat ``AppError`` is enough at this stage: there is no
domain/application/infrastructure split yet (see docs/architecture.md), so a
layered exception hierarchy would be speculative. It is introduced once real
business logic exists to justify separating domain errors from
infrastructure errors.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for application errors that map to an HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()},
    )


async def _handle_unexpected_exception(_request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register the global exception handlers on the given FastAPI app."""
    # Starlette types `add_exception_handler`'s handler parameter to accept
    # `Callable[[Request, Exception], ...]` — the broad base type. Our
    # handlers narrow the second parameter to a specific `Exception`
    # subclass, which is contravariant (unsound in general) from a type
    # checker's point of view, even though Starlette itself dispatches the
    # correct exception type at runtime based on the class passed as the
    # first argument here. Pyright is right to flag it in the general case;
    # these two are the one safe, intentional exception to that rule.
    app.add_exception_handler(AppError, _handle_app_error)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(
        RequestValidationError,
        _handle_validation_error,  # pyright: ignore[reportArgumentType]
    )
    app.add_exception_handler(Exception, _handle_unexpected_exception)
