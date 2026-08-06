# Agentic Learning Platform

Backend foundation for an AI Learning Assistant. This repository is currently in
**PR-001 — Project Foundation** stage: a minimal, clean, runnable FastAPI service
with no domain logic yet. See [`docs/architecture.md`](docs/architecture.md) for
the reasoning behind what is (and is not) here.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker + Docker Compose (optional, for containerized runs)

## Setup

```bash
uv sync
```

This creates a `.venv` and installs both runtime and development dependencies
from `uv.lock`.

## Running locally

```bash
cp .env.example .env
make run
```

The API will be available at `http://localhost:8000`.

- `GET /health` — liveness probe, always returns 200 once the process is up.
- `GET /ready` — readiness probe.

## Running with Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

## Development

```bash
make lint       # ruff check
make format     # ruff format
make typecheck  # pyright (strict mode)
make test       # pytest
make check      # lint + typecheck + test
```

## Project status

This is an early-stage foundation. Deliberately **not** implemented yet:
PostgreSQL/pgvector, AWS integration, Bedrock, LangChain/LangGraph, RAG,
document parsers, authentication, multi-tenancy, the embeddable widget, and
video support. These arrive in later, separately reviewed PRs.

## License

[MIT](LICENSE)
