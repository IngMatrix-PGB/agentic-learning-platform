"""Application-wide exception handling.

A single, flat ``AppError`` hierarchy is enough at this stage: PR-002
introduces real domain/application/infrastructure layers (see
docs/architecture.md), but each layer's own concrete exceptions are simple
subclasses of the same base rather than three parallel hierarchies — there
isn't yet enough distinct failure-handling behavior per layer to justify
that. Revisit if that changes.

Startup-time failures (dimension mismatch, migration conflicts) are
deliberately NOT part of this hierarchy: they should crash the process before
it starts serving traffic, not be caught and turned into an HTTP response.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for application errors that map to an HTTP response."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedDocumentError(AppError):
    """The uploaded file is not a PDF, or is a PDF with no extractable digital
    text (e.g. scanned-only pages) — OCR is explicitly out of scope."""

    status_code = status.HTTP_400_BAD_REQUEST


class DocumentTooLargeError(AppError):
    """The uploaded file exceeds ``settings.max_upload_size_mb``."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE


async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # `jsonable_encoder`, not a raw `exc.errors()` dict: a custom
    # `field_validator` raising `ValueError` (e.g. routes.query.QueryRequest's
    # max-length check) makes pydantic put the raw exception object itself
    # into each error's `ctx.error`, which plain `json.dumps` cannot serialize.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(exc.errors())},
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
