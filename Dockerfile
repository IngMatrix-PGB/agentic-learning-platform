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

# libgl1/libglib2.0-0 etc. are required at import time by opencv-python, a
# transitive dependency of docling's layout/table models — without them the
# process crashes on startup inside the slim base image.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --no-create-home appuser

WORKDIR /app

COPY --from=builder --chown=appuser:app /app/.venv ./.venv
COPY --from=builder --chown=appuser:app /app/src ./src
COPY --chown=appuser:app web ./web

# Cache directory for FastEmbed/Hugging Face model weights. Deliberately NOT
# populated during build — the model is downloaded lazily on first use and
# persisted in the `fastembed_cache` named volume mounted here in
# docker-compose.yml, so subsequent `docker compose up` runs reuse it instead
# of re-downloading.
RUN mkdir -p /app/.cache/fastembed && chown -R appuser:app /app/.cache

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["python", "-m", "agentic_learning_platform.main"]
