# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

# Official static uv binary, copied directly from Astral's published image —
# avoids a network-dependent `pip install uv` layer in the builder.
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /usr/local/bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home appuser

WORKDIR /app

COPY --from=builder --chown=appuser:app /app/.venv ./.venv
COPY --from=builder --chown=appuser:app /app/src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["python", "-m", "agentic_learning_platform.main"]
