# Architecture — PR-001 (Project Foundation)

This document explains the state of the repository after PR-001, and — just
as importantly — why it is deliberately minimal.

## What exists

```
src/agentic_learning_platform/
├── __init__.py
├── config.py      # Settings (Pydantic Settings), single source of runtime config
├── logging.py      # JSON structured logging, stdlib only
├── exceptions.py    # AppError + global FastAPI exception handlers
├── app.py           # create_app() factory
├── main.py          # process entrypoint (uvicorn)
└── routes/
    └── health.py     # GET /health, GET /ready
```

No `domain/`, `application/` or `infrastructure/` packages exist yet.

## Why no hexagonal architecture yet

A ports/adapters/domain split earns its keep when there is real domain
behavior to isolate from frameworks and I/O — a RAG pipeline, a document
store, an LLM provider. At this stage there is none: the only behavior is two
endpoints that report process health. Introducing `domain/application/
infrastructure` now would mean creating empty or near-empty layers purely in
anticipation of future work, which is the over-engineering this PR explicitly
avoids. The layered split is introduced in the PR that adds the first real
piece of domain logic, once there is something concrete to isolate.

## Why a flat `AppError` instead of a 3-layer exception hierarchy

For the same reason: a `DomainException` / `ApplicationException` /
`InfrastructureException` hierarchy only makes sense once those three layers
exist and can each fail in distinct ways. Today there is one error type that
maps to an HTTP response. It will be split when the layers it would separate
actually exist.

## Why no `lifespan` context manager yet

`lifespan` exists to manage resources that must be opened at startup and
closed at shutdown (database pools, connections). This PR opens no such
resource, so there is nothing for `lifespan` to manage. It is added in the PR
that introduces the first resource of that kind.

## Logging

Structured JSON logging is implemented with a small `logging.Formatter`
subclass over the standard library (`src/agentic_learning_platform/logging.py`).
No third-party logging library is introduced — a hand-rolled JSON formatter
is sufficient for "basic structured logging" and avoids adopting a larger API
surface (e.g. `structlog`) before there is anything non-trivial to log
(request correlation ids, tracing spans, etc.).

This applies uniformly to application logs *and* to uvicorn's own logs.
Uvicorn configures its `uvicorn`, `uvicorn.error` and `uvicorn.access` loggers
with their own (non-JSON) handlers and `propagate=False` as soon as
`uvicorn.run()` starts, which would otherwise bypass the root logger's
`JsonFormatter` entirely. `build_uvicorn_log_config()` is passed to
`uvicorn.run(..., log_config=...)` to strip those loggers' own handlers and
let them propagate to the already-configured root logger instead — so every
line written to stdout, whether it comes from application code or from
uvicorn itself (startup, shutdown, request access logs), is valid JSON, with
no message emitted twice.

## Type checking: Pyright over mypy

Pyright was chosen for this project because:

- It ships as a self-contained PyPI package (`pyright`). The package manages
  its own Node.js runtime automatically on first run (via its `nodeenv`
  dependency) — Node.js is still involved under the hood, but neither
  contributors nor CI have to install or configure it manually.
- It is the engine behind VS Code's Pylance, so the errors seen in CI match
  what a contributor sees in their editor.
- Its `strict` mode gives stronger default inference for modern typing
  constructs.

`mypy` remains a perfectly valid alternative; it was not chosen here for lack
of merit, but because Pyright better fits this project's editor/CI parity
goal. `src/` and `tests/` are both type-checked, though `tests/` relaxes a
small number of rules (`reportUnknownMemberType`, `reportUnknownVariableType`,
`reportUnknownArgumentType`) — this is a documented, scoped exception due to
`httpx`/`starlette`'s `TestClient` not being fully inferable under strict
mode, not a general relaxation of typing discipline.

## Container

`Dockerfile` is a two-stage build: a `builder` stage that installs
dependencies with `uv sync --frozen --no-dev --no-editable`, and a `runtime`
stage that only contains the resulting virtual environment, the application
source, and a non-root `appuser`. `docker-compose.yml` runs only the `api`
service — there is no database or other backing service to orchestrate yet.

## Explicitly out of scope for this PR

PostgreSQL, pgvector, AWS, S3, Bedrock, LangChain/LangGraph, RAG, embeddings,
document parsers, authentication, the embeddable widget, video support,
multi-tenancy, queues, Redis, and Terraform. Each of these is added in its own
PR, reviewed on its own merits, once there is a concrete reason to introduce
it.
