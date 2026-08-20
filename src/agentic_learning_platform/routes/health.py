"""Health and readiness endpoints."""

from typing import Literal

import asyncpg
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe: the process is up and answering requests."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse | JSONResponse:
    """Readiness probe: verifies the database pool can actually run a query,
    not just that the process is up."""
    pool: asyncpg.Pool = request.app.state.db_pool
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:  # readiness must be robust to any DB failure mode, not just specific ones
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )
    return HealthResponse(status="ok")
