# Architecture

This document explains the current state of the repository and, importantly,
*why* each addition happened when it did — the project deliberately avoids
introducing structure before there is real behavior to justify it.

## PR-001 — Project Foundation

A minimal, runnable FastAPI service: `GET /health`, `GET /ready`, typed
config, JSON logging, a flat exception hierarchy, Docker/CI. No domain logic,
so no `domain/`, `application/` or `infrastructure/` packages existed yet —
see the "Why hexagonal architecture now" section below for why that changed.

## PR-002 — Local RAG flow (PDF → citation)

The first real, demonstrable flow: upload a PDF, ask a question, get an
answer with a verifiable page citation, running entirely on PostgreSQL +
pgvector. This is the point where domain/application/infrastructure layering
started earning its keep — there is now real business logic (parsing,
chunking, retrieval, evidence-sufficiency, citation) to isolate from the
frameworks and I/O that implement it.

### Current structure

```
src/agentic_learning_platform/
├── app.py                        # FastAPI app factory + lifespan (migrations, DB pool, adapter wiring)
├── config.py                     # Settings — single source of runtime config
├── logging.py                    # JSON logging (app + uvicorn)
├── exceptions.py                 # AppError + UnsupportedDocumentError + DocumentTooLargeError
├── main.py                       # process entrypoint (uvicorn)
├── domain/
│   └── models.py                 # SourceDocument, DocumentChunk, SearchResult, Citation, QueryAnswer
├── application/
│   ├── ports/                    # the ONLY 4 interfaces in this codebase
│   │   ├── document_parser_port.py
│   │   ├── embedding_port.py
│   │   ├── vector_store_port.py
│   │   └── answer_generator_port.py
│   └── services/
│       ├── ingestion_service.py  # parse -> chunk -> embed -> persist (idempotent by checksum)
│       ├── retrieval_service.py  # embed question -> search -> evidence-sufficiency decision
│       └── query_service.py      # retrieve -> (short-circuit) -> generate -> attach citations
├── infrastructure/
│   ├── di.py                     # adapter selection by settings.runtime_mode (plain factory, no DI container)
│   ├── db/
│   │   ├── pool.py                # asyncpg pool with pgvector's codec registered
│   │   └── migrations/
│   │       ├── runner.py          # deterministic, versioned, dimension-aware SQL runner
│   │       └── sql/001_init_rag_schema.sql
│   ├── parsers/docling_parser_adapter.py
│   ├── chunking/page_chunking_strategy.py   # NOT a port — see below
│   ├── embeddings/{local_embedding_adapter.py, bedrock_embedding_adapter.py}
│   ├── vector_store/pgvector_vector_store_adapter.py
│   └── answer_generation/{extractive_answer_adapter.py, bedrock_answer_adapter.py}
└── routes/{documents.py, query.py, health.py}
```

### Why hexagonal architecture now (and only this much of it)

Ports exist for exactly four things: **embeddings**, **vector store**,
**document parser**, **answer generator** — each has two real, swappable
implementations (local vs. AWS, or Docling as the one parser). Chunking is
**not** a port: there is only one implementation and no plan to swap it in
this PR, so an interface there would be speculative. `infrastructure/di.py`
is a plain factory function, not a DI container library — with four ports
and two modes, a container would be pure ceremony.

### Two execution modes, never mixed

`settings.runtime_mode` is `"local"` or `"aws"`, set explicitly — **never**
auto-detected from AWS credentials. Each mode selects a *matching pair* of
embedding + answer-generation adapters; `infrastructure/di.py` cannot produce
a mixed combination.

- **`local`** (default): FastEmbed (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`,
  384 dimensions, ONNX Runtime — no PyTorch, no external service) for
  embeddings, and a purely extractive answer "generator" (returns the
  retrieved fragment(s) verbatim, no LLM call at all). This mode demonstrates
  parsing, chunking, embeddings, retrieval, and citations — **not** answer
  quality, which is validated separately in `aws` mode.
- **`aws`**: AWS Bedrock Titan Text Embeddings V2 (dimension configured
  explicitly, 1024 by default) for embeddings, and `ChatBedrockConverse`
  (via `langchain-aws`) for generation.

The embedding dimension is a hard, fixed property of a given database — it
is not something that can differ between the two modes against the same
schema (see "Dimension validation" below).

### Document parsing: Docling, no OCR

`DoclingParserAdapter` disables Docling's OCR pipeline
(`PdfPipelineOptions.do_ocr = False`) — this PR only accepts PDFs with
digital (non-scanned) text, per its explicit scope. A PDF that fails to
convert, or converts with zero extractable text on every page, raises
`UnsupportedDocumentError` (400) rather than silently producing empty chunks.
`PyMuPDF` was deliberately not used here — its `AGPL-3.0` license is
incompatible with a commercial product without a paid Artifex license;
Docling (MIT, Linux Foundation AI & Data) and `pdfplumber` (MIT) do not have
that problem.

### Migrations: deterministic, versioned, dimension-aware — no Alembic

Migrations are plain, explicit `.sql` files under
`infrastructure/db/migrations/sql/`, with exactly one controlled
substitution: `{{EMBEDDING_DIMENSION}}`. `infrastructure/db/migrations/runner.py`:

1. Renders each migration file with the *current* `settings.embedding_dimension`.
2. Records `(version, checksum of the rendered SQL, embedding_dimension, applied_at)`
   in a `schema_migrations` bookkeeping table.
3. On every subsequent run (including every app startup), re-renders the same
   files and compares against what is recorded. A different dimension *or* a
   different checksum for an already-applied version raises
   `MigrationConflictError` immediately — the process crashes before serving
   traffic rather than silently running against a schema that does not match
   its own configuration.

This is also how "declared vs. configured dimension" validation at startup
is satisfied: there is no separate check function — re-running migrations
*is* the check, every time the app boots. It is also why switching
`runtime_mode` against an existing database with a different dimension is
refused: it would hit exactly this same conflict.

No Alembic: at four columns and one table relationship, a migration
framework would not remove meaningful complexity — plain, checksummed SQL
files are simpler to read, review, and reason about at this scale.

### Local embeddings: FastEmbed, not Ollama

An earlier version of this plan considered Ollama as the local-mode
embedding provider. It was rejected: Ollama is a separate running service —
effectively a second model *provider*, which the approved scope explicitly
ruled out ("no introducir un proveedor adicional"). FastEmbed (`fastembed`,
Qdrant) runs the embedding model in-process via ONNX Runtime — no PyTorch, no
extra service, no extra provider — while still producing real, meaningful
embeddings (unlike a deterministic hash-based stub, which would make
retrieval results meaningless and defeat the point of a "demonstrable" local
mode). The model is **not** downloaded during `docker build` — it is
downloaded lazily on first use and cached in the `fastembed_cache` named
Docker volume, so only the very first `docker compose up` needs internet
access for this.

Docling *also* downloads model weights on first use (a layout model, even
with OCR disabled) — this was discovered empirically while building this PR,
not planned for upfront. It uses Hugging Face Hub's default cache location
inside the container, which is not yet pinned to its own named volume in
this PR; a cold container will re-download Docling's layout model. This is a
known, documented gap, not an oversight — see the risks section of the PR-002
summary for the follow-up.

### Why `DB_HOST` defaults to `localhost`, not `postgres`

`pytest` and `make run` run directly on the host, reaching Postgres via
docker-compose's published `5432:5432` port — `localhost` is correct there.
The `api` container itself cannot reach a sibling container via `localhost`;
it needs the Compose service name `postgres`. `docker-compose.yml`
overrides `DB_HOST=postgres` explicitly in the `api` service's `environment:`
block, regardless of what `.env` says — `.env`/`.env.example`'s
`DB_HOST=localhost` is for the host-side case only.

### Logging (unchanged from PR-001, still holds)

Structured JSON logging is implemented with a small `logging.Formatter`
subclass over the standard library (`src/agentic_learning_platform/logging.py`).
It applies uniformly to application logs *and* uvicorn's own logs — see the
PR-001-era explanation retained below. Startup logs the active
`runtime_mode`, the resolved embedding model name, and its dimension as a
single structured JSON line, so it is always possible to tell which mode a
running instance is actually using without inspecting its configuration
directly.

Uvicorn configures its `uvicorn`, `uvicorn.error` and `uvicorn.access`
loggers with their own (non-JSON) handlers and `propagate=False` as soon as
`uvicorn.run()` starts, which would otherwise bypass the root logger's
`JsonFormatter` entirely. `build_uvicorn_log_config()` is passed to
`uvicorn.run(..., log_config=...)` to strip those loggers' own handlers and
let them propagate to the already-configured root logger instead — so every
line written to stdout, whether it comes from application code or from
uvicorn itself, is valid JSON, with no message emitted twice.

Known, undocumented-until-now limitation: third-party libraries used in this
PR (Docling, its OCR/layout dependencies, RapidOCR, transformers/torch) print
their own unstructured, non-JSON, colored log output directly, bypassing our
`JsonFormatter` entirely (some configure their own handlers, some just
`print()`). This was observed during manual testing of the Docling adapter.
It is not fixed in this PR — silencing third-party logging noise fully would
require per-library configuration that was judged out of scope here — but it
means `docker compose logs` will show some non-JSON lines during PDF parsing
that do not originate from this application's own code.

### Type checking: Pyright over mypy (unchanged from PR-001)

Pyright was chosen because it ships as a self-contained PyPI package
(managing its own Node.js runtime automatically), matches VS Code's Pylance
so editor and CI errors agree, and its `strict` mode gives stronger default
inference. `mypy` remains a valid alternative; it was not chosen for lack of
merit.

Two additional scoped relaxations were added in PR-002, alongside PR-001's
existing `tests/`-only relaxation for `httpx`/`TestClient`:

- `src/agentic_learning_platform/infrastructure/` and
  `src/agentic_learning_platform/routes/` relax `reportMissingTypeStubs`,
  `reportUnknownMemberType`, `reportUnknownVariableType` and
  `reportUnknownArgumentType`. `asyncpg` ships no `py.typed` marker and most
  of its public API (`Pool.acquire`, `Connection.execute`/`fetch`/
  `fetchrow`/`transaction`, `asyncpg.connect`, ...) has genuinely untyped
  parameters in its own source — not a stub *gap* but an untyped library.
  `domain/` and `application/` never touch raw `asyncpg` types directly
  (only our own typed ports and domain objects flow through them) and stay
  fully strict.
- `tests/` gained the same `reportMissingTypeStubs = false` for the same
  reason, since some tests exercise the database directly.

### Container

`Dockerfile` remains the PR-001 two-stage build (`builder` installs with
`uv sync --frozen --no-dev --no-editable`; `runtime` is non-root). PR-002
adds system libraries required at import time by `opencv-python` (a
transitive dependency of Docling's layout/table models: `libgl1`,
`libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1` — without them the
process crashes on startup in the `slim` base image) and pre-creates
`/app/.cache/fastembed`, owned by the non-root user, as the mount point for
the `fastembed_cache` named volume.

`docker-compose.yml` now runs two services: `postgres` (the official
`pgvector/pgvector:pg16` image, with a healthcheck and a named volume for
data persistence) and `api` (depends on `postgres` being healthy, mounts the
`fastembed_cache` named volume, overrides `DB_HOST` as described above).

### Explicitly out of scope for this PR

LangGraph (the retrieve → evaluate → generate → cite flow is a small linear
async function with one conditional branch — introducing LangGraph's
state-graph/checkpointer machinery for this would be more ceremony than the
flow itself, not less; it is introduced once a real multi-branch or
tool-using flow needs it), the embeddable widget, streaming, authentication,
multi-tenancy, S3, Terraform, ECS, Langfuse, DeepEval, Ragas, DOCX/PPTX/XLSX,
diagrams, OCR, video, and Bedrock Knowledge Bases. Each is added in its own
PR, reviewed on its own merits, once there is a concrete reason to introduce
it.
