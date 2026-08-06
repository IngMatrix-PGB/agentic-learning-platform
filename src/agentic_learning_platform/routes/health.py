"""Health and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe: the process is up and answering requests."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready() -> HealthResponse:
    """Readiness probe.

    There are no external dependencies (database, cache, etc.) yet, so
    readiness is currently equivalent to liveness. This will start checking
    real dependencies once they exist.
    """
    return HealthResponse(status="ok")
