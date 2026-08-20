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

### Explicitly out of scope for PR-002

LangGraph (the retrieve → evaluate → generate → cite flow is a small linear
async function with one conditional branch — introducing LangGraph's
state-graph/checkpointer machinery for this would be more ceremony than the
flow itself, not less; it is introduced once a real multi-branch or
tool-using flow needs it), the embeddable widget, streaming, authentication,
multi-tenancy, S3, Terraform, ECS, Langfuse, DeepEval, Ragas, DOCX/PPTX/XLSX,
diagrams, OCR, video, and Bedrock Knowledge Bases. Each is added in its own
PR, reviewed on its own merits, once there is a concrete reason to introduce
it.

## PR-003 — Embeddable chat widget + streaming

The first visual, end-to-end experience: a demo course page embeds a small
widget that asks questions against the PR-002 RAG flow and gets answers
back progressively over SSE, with citations. No change to
`domain/`, `application/`, or `infrastructure/` — this PR is entirely a thin
transport layer (one new route) plus two static frontend files, reusing
`QueryService` exactly as PR-002 built it.

### New surface

```
src/agentic_learning_platform/routes/query_stream.py   # POST /v1/query/stream
web/demo/index.html                                     # served at GET /demo
web/widget/widget.js                                     # served at GET /widget/widget.js
```

Both `web/` directories are mounted via Starlette's `StaticFiles` in
`app.py` — no new backend dependency, no npm, no bundler, no frontend
framework. `Dockerfile` copies `web/` into the runtime image alongside `src/`.

### Why the RAG pipeline runs *before* the stream opens, not inside it

`query_stream()` calls `await query_service.answer(question)` — the exact
same call `/v1/query` makes — and only *then* returns a `StreamingResponse`
that paces the already-complete `QueryAnswer` out over SSE. This is
deliberate: once SSE headers are sent, the HTTP status is locked in at 200;
an error inside the generator can only be smuggled to the client as another
SSE event, not as a proper HTTP error status. Retrieval errors, evidence-check
logic, generator failures, and input validation all still produce ordinary
HTTP error responses (422, 500, ...) exactly as they do for `/v1/query`. The
generator's own `event: error` exists purely as a defensive fallback for a
failure *during emission itself* (e.g. the client disconnecting mid-stream)
— it is not, and must not become, the error-handling path for the RAG
pipeline.

### Streaming is transport-level pacing, not real model streaming — in *either* mode

`ExtractiveAnswerGeneratorAdapter` returns its full answer synchronously;
`BedrockAnswerGeneratorAdapter` calls `ChatBedrockConverse.ainvoke` (not
`.astream`). Neither adapter can produce tokens incrementally today, so
`query_stream.py` takes the finished answer text and paces it out
word-by-word with a small `asyncio.sleep` between words
(`settings.stream_chunk_delay_ms`, default 40ms) — this exists to demonstrate
the SSE contract and the widget's progressive-rendering UX, not to fake an
LLM "thinking". This applies identically regardless of `runtime_mode`. Real
token-by-token streaming from Bedrock is future scope: it would add an
`astream`-shaped method to `IAnswerGeneratorPort` (a real port change, not
something this PR should reach for) and a second code path in the route that
uses it instead of pacing a finished string.

### SSE contract

```
event: token
data: {"text": "..."}
      ⋮ (one per word)
event: citations
data: {"citations": [{"source": "...", "page": N, "chunk_id": "...", "score": 0.NN}]}

event: done
data: {}
```

`citations` always carries the same structured `Citation` fields PR-002
already exposes via `/v1/query` (`source`, `page`, `chunk_id`, `score`) —
the client never infers a citation from generated text. The
"insufficient evidence" case is not special-cased for streaming: it is the
same `QueryAnswer` (fixed message, `citations=[]`) PR-002 already produces,
just paced the same way as any other answer.

### SSE over `POST`, not native `EventSource`

The browser's native `EventSource` only issues `GET` requests with no
request body, which would force the question into a query string —
worse for a length-limited, potentially sensitive question than a JSON
POST body. The widget instead calls `fetch()` and manually parses the
`ReadableStream` body by splitting on blank lines and reading `event:`/
`data:` prefixes. No WebSockets: nothing here needs the client to send data
mid-response, so the extra complexity (a persistent bidirectional
connection, its own reconnection/backpressure concerns) has no
justification yet.

### Widget: vanilla Web Component, not a framework

`<learning-assistant-widget>` is a single-file Custom Element using Shadow
DOM for style isolation — no React/Vue/Angular, no bundler, matching the
brief's "mantenerlo deliberadamente pequeño". Conversation history lives in
the component's own in-memory state for the page's lifetime only (no
persistence — not asked for). Everything that comes from the API (answer
text, citation fields, error messages) is written via `textContent` or
plain DOM node creation — **never** `innerHTML` — which is what closes XSS
here without needing a sanitizer dependency.

### CORS: explicit, never `"*"`

`CORSMiddleware` is configured from `settings.cors_allowed_origins_list`
(parsed from a comma-separated `CORS_ALLOWED_ORIGINS` env var, following the
same computed-`@property` pattern as `database_dsn`), restricted to `GET`/
`POST` and the `Content-Type` header. `/demo` is served by this same FastAPI
app, so it never needs CORS at all — this configuration exists solely for
embedding the widget on a *different* origin (a real client portal), and the
shipped default (`http://localhost:8000`) is for local development only.

### Shared input validation: one `QueryRequest`, one limit

`routes/query.py`'s `QueryRequest` (used by both `/v1/query` and
`/v1/query/stream`) gained a `max_question_length` check via a
`field_validator`, not `Field(max_length=...)` — the latter would bind
`get_settings()`'s value once at module-import time; the validator reads
`get_settings()` per-request instead, so it reflects whatever `Settings` is
actually active (this also matters for tests, which override env vars and
clear `get_settings`'s cache per test).

### Explicitly out of scope for PR-003

Real Bedrock token streaming, authentication, multi-tenancy, LangGraph,
Terraform/ECS/RDS/S3/AWS deployment, Bedrock Knowledge Bases, DOCX/PPTX/XLSX,
OCR, video, multimodal images, Langfuse/Ragas/DeepEval, analytics, quizzes,
and agent/tool-calling. No speculative infrastructure was added for any of
these.

### Known limitations

- The widget has not been exercised inside a host page with a strict
  Content-Security-Policy; a CSP blocking external scripts would need an
  explicit allowance for `<script src="/widget/widget.js">`.
- `stream_chunk_delay_ms` word-by-word pacing is a fixed, simple scheme — it
  does not account for very long answers needing a shorter per-word delay to
  stay feeling responsive; not tuned further since this is a demo, not a
  production UX.
- ~~No corpus isolation~~ — **resolved in PR-004** (see below): retrieval is
  now scoped to `organization_id`/`course_id` in SQL, and `pytest` runs
  against its own ephemeral database instead of sharing the demo's.
- `app.py`'s `_WEB_DIR = Path("web")` resolves relative to the current
  working directory, which happens to be correct in all three validated
  environments (`pytest`, `make run`, the Docker image) but is an implicit
  assumption, not enforced by a setting. Minor technical debt — revisit only
  if a future deployment changes the process's working directory (it would
  fail loudly at startup via `StaticFiles`' own `RuntimeError`, not silently).
- The widget has no client-side request timeout or `AbortController` — a
  hung server response leaves the "Pensando..." indicator and a disabled
  composer indefinitely. Deferred as a future UX-resilience improvement, not
  needed for this PR's demo scope.

## PR-004 — Context isolation & authorization foundation

PR-002/PR-003 confirmed empirically (contaminated test/demo corpus) that
retrieval had no scope at all: `PgVectorStoreAdapter.search()` ran
`ORDER BY embedding <=> $1 LIMIT $2` over the entire `document_chunks` table,
with no `WHERE`. This PR closes that at the SQL layer and adds a minimal,
explicitly-provisional authorization boundary — no LangGraph, hybrid
retrieval, reranking, real auth (Cognito/OIDC/JWT), or organization/course
administration are introduced here; each is out of scope until there is a
concrete reason to build it.

### Data model: `organization_id`/`course_id`, scoped to both tables

`source_documents` and `document_chunks` both gained `organization_id` and
`course_id` (`TEXT`, not `UUID` — see "Why TEXT, not UUID" below). This is
denormalized on purpose: no `organizations`/`courses` tables exist yet (that
belongs to the portal's identity system, whose shape isn't known), and
duplicating the two columns onto `document_chunks` — not just
`source_documents` — is what lets retrieval filter with a plain `WHERE`
directly on the table carrying the HNSW index, in one query, before
`ORDER BY ... LIMIT`:

```sql
SELECT id, document_id, source_name, page_number, chunk_index, content,
       1 - (embedding <=> $1) AS score
FROM document_chunks
WHERE organization_id = $2 AND course_id = $3
ORDER BY embedding <=> $1
LIMIT $4
```

A `JOIN` back to `source_documents` for the same filter would work
correctly too (the `WHERE` still runs before `LIMIT` either way), but
pgvector's ANN index cannot be used as effectively when the filter column
lives on the joined table rather than directly on `document_chunks` — this
denormalization is the standard pattern for multi-tenant pgvector search,
not a deviation from normalization for its own sake. A composite btree
index `(organization_id, course_id)` on `document_chunks` backs this filter.

Both tables' scope columns are only ever written together, from the same
`SourceDocument`/`DocumentChunk` objects, in the single transaction
`PgVectorStoreAdapter.insert_document()` already used — but an adversarial
review of this PR correctly pointed out that this was, at first, only
*application code discipline* (one call site), not something the schema
itself enforced. Migration 002 now closes that gap structurally:

```sql
ALTER TABLE source_documents
    ADD CONSTRAINT source_documents_id_org_course_key
    UNIQUE (id, organization_id, course_id);

ALTER TABLE document_chunks
    ADD CONSTRAINT document_chunks_document_id_fkey
    FOREIGN KEY (document_id, organization_id, course_id)
    REFERENCES source_documents (id, organization_id, course_id)
    ON DELETE CASCADE;
```

The composite FK replaces the original single-column
`document_chunks.document_id -> source_documents.id` FK rather than
supplementing it: any row satisfying the 3-column match necessarily
satisfies the 1-column one too, so keeping both would only add a redundant
constraint enforcing a strict subset of the same rule. `ON DELETE CASCADE`
is unchanged in effect — deleting a `source_documents` row still deletes all
of its chunks. A chunk insert whose `organization_id`/`course_id` doesn't
match its `document_id`'s row in `source_documents` is now rejected by
PostgreSQL itself (`asyncpg.ForeignKeyViolationError`), inside the same
transaction `insert_document()` already runs — verified against real
Postgres in `test_insert_document_rejects_a_chunk_scoped_to_a_different_course_than_its_document`.

### Why TEXT, not UUID

`organization_id`/`course_id` are opaque strings, in both `RequestContext`
(Python) and the database (`TEXT` columns) — not `UUID`. Every other ID in
this codebase is a `UUID` generated internally (`SourceDocument.id`,
`DocumentChunk.id`, ...), but these two identify entities that will
eventually come from an external identity provider (Cognito, a generic
OIDC provider, or an LMS) whose ID format is not yet decided. Forcing UUID
now risks rejecting a legitimate external ID later for a purely internal
reason. `user_id` is `str` for the same reason. asyncpg parameterizes every
query (`$1`, `$2`, ...), so accepting arbitrary opaque strings here carries
no SQL injection risk.

### Idempotency: scoped, not global

`source_documents.checksum_sha256 UNIQUE` (global) became
`UNIQUE (organization_id, course_id, checksum_sha256)`: the same PDF bytes
(e.g. a shared syllabus) can now exist as independent documents in different
courses, while re-uploading the same bytes into the *same* course remains a
no-op (`already_existed: true`, `chunks_created: 0`), exactly as PR-002
established.

### Migration: `002_add_org_course_scope.sql`, requires a clean database

Cannot edit `001_init_rag_schema.sql` (the runner's checksum tracking would
raise `MigrationConflictError` against any already-migrated database). The
new migration's `ADD COLUMN ... NOT NULL` fails against a table with
existing rows — since there is no production data yet (and no meaningful
placeholder scope for old local demo rows), the migration requires a clean
database rather than backfilling a fake scope. Run
`docker compose down -v` before the first boot on this schema version.

### `RequestContext` and `IAuthorizationContextProvider`

```python
@dataclass(frozen=True, slots=True)
class RequestContext:
    organization_id: str
    course_id: str
    user_id: str
```

Lives in `domain/models.py` alongside the other framework-free models.
`IAuthorizationContextProvider` (`application/ports/authorization_context_port.py`)
is a new port, following the same `ABC` pattern as the four PR-002 ports:
`resolve(*, organization_id, course_id, user_id) -> RequestContext`, raising
`MissingAuthorizationContextError` (401) if any of the three is missing or
blank. `infrastructure/authorization/dev_header_provider.py`'s
`DevHeaderAuthorizationContextProvider` is the **only** implementation in
this PR — wired via a small `build_authorization_context_provider(settings)`
factory in `di.py`, mirroring `build_adapters`. A future PR replaces this one
factory function with a real JWT/OIDC-backed provider; `QueryService`,
`IngestionService`, the domain, and every route stay unchanged, because they
only ever depend on the `RequestContext` the port already resolved, never on
how it was resolved.

**`X-Organization-Id` / `X-Course-Id` / `X-User-Id` are a development
authorization context / trusted local context — NOT authentication.** Any
client can set any value for them; there is no verification of who is
actually asking. This is explicitly acceptable for local development and
demo purposes only, and must never be treated as a security boundary in any
real deployment. `user_id` flows through for logging/audit only — it never
participates in the retrieval scope filter (that's `organization_id`/
`course_id` alone).

### Request flow

`routes/authorization.py`'s `get_request_context` is a single shared FastAPI
dependency used identically by `/v1/documents`, `/v1/query`, and
`/v1/query/stream` — it resolves the three headers into a `RequestContext`
before the route body runs. Neither request body (`QueryRequest`, the
multipart upload) has any organization/course field at all, so there is no
client-supplied value that could contradict the resolved context — the
scope is structurally the header-resolved one or the request fails, with no
third option to reconcile.

`IngestionService.ingest(...)`, `RetrievalService.retrieve(...)`, and
`QueryService.answer(...)` all gained a required `context: RequestContext`
parameter (not injected via a constructor — these services are process-wide
singletons on `app.state`, built once at startup; scope only exists
per-request, so it has to travel as a method argument). `IVectorStorePort`'s
`find_by_checksum`/`search` gained required `organization_id`/`course_id`
keyword parameters for the same reason — making them required, not optional,
turns "forgot to scope a query" into a type error `pyright --strict` catches,
not a convention someone can silently skip.

For `/v1/query/stream`, context resolution happens exactly like question
validation already did in PR-003: before `StreamingResponse` is
constructed, so a missing/invalid context is a normal HTTP 401, never a
broken SSE stream. The `token* → citations → done` contract is otherwise
unchanged.

### Widget/demo

The widget gained `organization-id`/`course-id`/`user-id` attributes (same
pattern as the existing `api-base`), sent as the three headers on every
`fetch()` call. `web/demo/index.html` sets fixed dev values with a visible
HTML comment warning they are not real authentication.
`scripts/demo_local.sh`'s `curl` calls carry the same headers. `CORSMiddleware`'s
`allow_headers` now includes the three custom headers — otherwise a
cross-origin widget's preflight would be rejected by the browser before the
request is ever sent (same-origin requests, like the `/demo` page's, never
needed CORS at all).

### Test database isolation

`tests/conftest.py` gained a session-scoped `_isolated_test_database`
fixture: it issues `CREATE DATABASE pytest_<random>` on the same Postgres
server the demo uses (the `agentic_learning` role created by the official
Postgres image is a superuser within its own container, so `CREATEDB` is
already available — no new credentials needed), points `Settings` at it for
the whole test session, and drops it at teardown. Real Postgres/pgvector,
zero mocks, and zero new Docker services — `pytest` no longer shares any
state with `docker compose up`'s manual demo database. The `client` fixture
also gained default `X-Organization-Id`/`X-Course-Id`/`X-User-Id` headers
(httpx merges per-request headers over client defaults), so every existing
PR-001/002/003 test kept working without being individually edited.

### The adversarial test

`tests/test_corpus_isolation.py` uploads byte-for-byte identical PDF content
into `org-A/course-A`, `org-A/course-B`, and `org-B/course-A` — the same
`course_id` string ("course-A") reused across two different organizations,
deliberately. Identical content means identical FastEmbed embeddings, which
means an unscoped or incorrectly-scoped query would tie on similarity score
and could easily return another scope's chunks in the top-k. The test
asserts on actual `chunk_id`s returned in each scope's citations — pairwise
disjoint across all three scopes, both directions at once — never just on
HTTP status. The same property is verified again for `/v1/query/stream`
against `/v1/query`, since both must resolve context identically.

### Explicitly out of scope for PR-004

Cognito, real JWT/OIDC, a login UI, IAM Identity Center integration,
`organizations`/`courses` CRUD administration, complex roles/permissions,
LangGraph, BM25/RRF/reranking/hybrid retrieval, advanced evals, real Bedrock
token streaming, Terraform/ECS/RDS/S3/AWS deployment. Each is added in its
own PR, once there is a concrete reason to introduce it.

### Known limitations

- The dev header provider is, by construction, trivially spoofable by any
  client — this is the entire, explicit point of it being DEV ONLY; it must
  be replaced before any real deployment, not hardened in place.
- `organization_id`/`course_id` have no registry to validate against (no
  `organizations`/`courses` tables) — any non-blank string is accepted as a
  valid scope today. Acceptable pre-launch; revisit once the identity
  provider decision is made.
- pgvector's ability to use the HNSW index efficiently alongside an
  additional `WHERE` filter is a known nuanced topic across pgvector
  versions; not a concern at this MVP's scale, but worth revisiting if a
  single course's chunk count grows very large.
- `MissingAuthorizationContextError`'s message names exactly which headers
  were missing/blank — acceptable for a DEV-ONLY mechanism, but this
  specific, mechanism-describing message should be revisited (generalized to
  a plain 401 with no internal detail) once a real auth provider replaces
  `DevHeaderAuthorizationContextProvider`. Deliberately not changed now —
  flagged in code review, deferred rather than touched speculatively ahead
  of that replacement.
- The `assert` in `DevHeaderAuthorizationContextProvider.resolve()` exists
  only for pyright's type narrowing; the actual validation is the preceding
  `if not all(values): raise` (a plain `if`, not the `assert`), so this does
  not depend on Python being run without `-O` — confirmed neither the
  Dockerfile nor CI ever pass that flag. Noted here only because it looks,
  at a glance, like the assert is load-bearing for security.

## PR-005 — RAG Evals & Quality Baseline

A **measurement** PR, not an improvement one: it exists to produce a
reproducible, honest baseline of the current (`local`, vector-only) RAG
system's quality, so a future PR-006 (Hybrid Retrieval) has something real
to compare against. **No retrieval/chunking/embedding/threshold/ranking
code, and no `QueryService`/`IngestionService`/pgvector query, was modified
to build this** — the eval harness is entirely additive, calling the exact
same production services (`RetrievalService`, `QueryService`,
`IngestionService`, `infrastructure.di.build_adapters`) the app itself uses.
A discovered quality issue (see "What this baseline found" below) is
reported here, not fixed — fixing it is PR-006's job, once it exists to
improve retrieval quality specifically.

### Why `RetrievalService` (raw) and `QueryService` (post-threshold) are both used

`RetrievalService.retrieve()` already returns the *complete* ranked
`list[SearchResult]` (up to `retrieval_top_k`), independent of the evidence
threshold. `QueryService.answer()` is where the threshold decision happens —
when `has_sufficient_evidence` is `False`, it returns `citations=[]`,
discarding the ranked results entirely. Using `QueryService` alone for
Recall@K would conflate two different questions this PR needs to answer
separately: "did retrieval find the right chunk?" (a ranking question) vs.
"did the system decide there was enough evidence?" (a threshold question).
So:

- **Recall@1/3/5, MRR** — computed from `RetrievalService.retrieve()`'s raw
  results, *before* the threshold is applied.
- **Citation Accuracy, No-Evidence Accuracy, False Positive/Negative Rate** —
  computed from `QueryService.answer()`, *after* the threshold is applied.

No changes were needed to either service to expose this — both already
returned everything required.

### Golden dataset: `eval_data/golden_dataset.v1.json`

32 cases (26 answerable, 6 no-evidence), each identified by
`expected_source` + `expected_pages` — **never `expected_chunk_ids`**:
`chunk_id`s are `uuid4()`-generated at ingestion time and are not stable
across the deterministic re-ingestion this harness performs on every run
(see below); pinning to them would make the dataset fragile for no benefit,
since source/page is already the stable identity the rest of this
codebase's tests use. Categories (by question-design intent, not by a
property the harness enforces):

| Category | Count | Tests |
|---|---|---|
| A — direct evidence | 6 | literal term match |
| B — paraphrase | 5 | semantic retrieval, no literal term overlap |
| C — related terms/synonyms | 3 | different vocabulary than the source text |
| D — ambiguous | 3 | vague phrasing that could plausibly match more than one chunk |
| E — no-evidence | 6 | genuinely unrelated questions |
| F — same-course distractor | 3 | lexically-overlapping but wrong document in the same course |
| G — cross-course | 4 (2 pairs) | near-duplicate content in a different course, same organization |
| H — cross-organization | 2 (1 pair) | near-duplicate content in a different organization entirely |

**32 cases, 28 unique question formulations.** Three groups intentionally
reuse question text — this is not incidental, it is what a *paired*
cross-scope comparison means: G1/G2 (and G3/G4) *must* ask the identical
question against two different courses for the pairing to test anything;
H1/H2 the same, across two organizations. The one genuinely avoidable
overlap (flagged in code review) is that `A1-incident-direct` happened to
land on the exact same natural phrasing as G1/G2
(*"¿Qué es la gestión de incidentes?"*) — A1 was not required to match, it
simply used the most direct wording independently. The three duplicate
groups, exactly:

- `A1-incident-direct`, `G1-crosscourse-101-literal`, `G2-crosscourse-201-literal`
- `G3-crosscourse-101-paraphrase`, `G4-crosscourse-201-paraphrase`
- `H1-crossorg-primary`, `H2-crossorg-secondary`

`load_golden_dataset()`/the report surface this honestly rather than
implying 32 independent signals: the report's `num_unique_questions` field
(`report.py`) is computed separately from `num_cases`, and
`tests/evals/test_dataset.py::test_shipped_dataset_has_exactly_the_documented_duplicate_questions`
pins down that these three groups are the *only* duplication, so a new,
undocumented one would fail the test rather than pass silently.

Versioned by filename (`v1`) — a dataset change significant enough to
affect comparability gets a new file, visible in the diff, rather than an
internal version field that could silently drift from the file's actual
content. Validated at load time (`dataset.py`): no blank `category`, and
every `category` prefix must be one of `A`-`H` — an unrecognized or missing
category fails fast rather than silently not counting toward any coverage
check.

#### Categories B and C, revised after adversarial review

An adversarial review of the first version of this dataset found that
categories B ("paraphrase") and C ("related terms") retained substantial
literal overlap with the source text — e.g. the original B1
(*"¿Cómo se restaura un servicio interrumpido lo más rápido posible?"*)
reused five consecutive words from the source verbatim
(*"...restaurar el servicio interrumpido lo mas rapido posible..."*),
making it a weak test of genuine semantic-only retrieval despite its
category label. All 5 B cases and all 3 C cases were rewritten by semantic
intent alone — reformulating what the source page *means* without reusing
its distinctive phrases — **before** running the evaluator, and were not
revisited afterward based on the resulting scores (see "What this baseline
found" below for the honest before/after). `expected_source`/`expected_pages`
were re-verified against the corpus and left unchanged for every case — the
ground truth was already correct, only the question wording changed.

### Synthetic evaluation corpus

Six short documents (`evals/corpus.py`), generated via FPDF at eval-run
time (same pattern as `tests/conftest.py`'s `sample_pdf_bytes` — no binary
fixture file, no licensing question), spanning IT service management
topics (Incident/Problem/Change Management, SLAs, Asset Management/CMDB,
Support Tiers, a Security Policy) plus two deliberate near-duplicates of
the Incident Management page: one in a second course of the same
organization, one in a second organization entirely — authored specifically
to give categories G and H something real to fail against if isolation
were ever broken.

### Metric definitions

- **Recall@K** (K ∈ {1,3,5}): fraction of answerable cases where a result
  matching `(expected_source, page ∈ expected_pages)` appears within the
  first K raw retrieval results.
- **MRR**: mean of `1/rank` over answerable cases (rank = 1-indexed position
  of the first matching raw result; `0` if no match within `retrieval_top_k`).
- **Citation Accuracy**: fraction of answerable cases where
  `has_sufficient_evidence` is `True` **and** at least one returned citation
  matches `(expected_source, page ∈ expected_pages)` — a citation is never
  scored correct independent of the sufficiency decision that produced it.
- **No-Evidence Accuracy**: fraction of no-evidence cases correctly rejected
  (`has_sufficient_evidence == False`) — a plain true-negative rate.
- **False Positive Rate**: `1 - No-Evidence Accuracy` — no-evidence cases the
  system incorrectly treated as having evidence.
- **False Negative Rate**: fraction of answerable cases incorrectly rejected
  as insufficient — real evidence existed but the threshold (or a retrieval
  miss) caused a rejection.
- **Groundedness (local)**: fraction of the extractive answer's segments
  (split on the `"\n\n---\n\n"` separator `ExtractiveAnswerGeneratorAdapter`
  joins multiple pieces of evidence with) that appear verbatim among the
  retrieved evidence's own content. Expected to be `1.0` in `local` mode by
  construction — the extractive generator never paraphrases, so there is
  nothing to hallucinate. Defined generally (not hardcoded to `1.0`) because
  the same check against a future real-generation (Bedrock) answer would be
  genuinely informative — no `IAnswerQualityPort`/LLM-judge abstraction was
  built for that yet, deliberately: that interface should be designed
  against a real generation case, not speculatively (see "Explicitly out of
  scope" below).

All of the above are pure Python (`evals/metrics.py`) — no Ragas, DeepEval,
or other eval framework. None of these formulas need semantic/LLM judgment;
adding one of those frameworks now would import a runtime built around
LLM-as-judge to solve a problem (deterministic structural comparison) this
PR doesn't have.

### Latency

Measured in-process, isolated around `RetrievalService.retrieve()` alone
(embedding + SQL search combined) — not via HTTP/ASGI, which would conflate
retrieval latency with unrelated transport overhead. `mean`/`p50`/`p95` over
one sample per case, sequential execution, no concurrency — a same-environment
PR-005-vs-PR-006 comparison tool, explicitly not an infrastructure/capacity
benchmark.

### Database isolation

The harness owns a dedicated database (`{db_name}_eval`, e.g.
`agentic_learning_eval`) — dropped and recreated (`DROP DATABASE IF EXISTS
... WITH (FORCE)` + `CREATE DATABASE`, via the new
`infrastructure.db.database_admin.recreate_database`) at the start of every
`make eval` run, for full determinism, and left in place afterward so its
contents can be inspected when a result looks surprising. This is a third,
separate database from both the demo's (`agentic_learning`) and `pytest`'s
own ephemeral per-session one (`tests/conftest.py`) — none of the three ever
share data. Every golden case carries its own `organization_id`/`course_id`,
resolved into a `RequestContext` per case exactly as a real request would be
— the harness never performs a global, unscoped retrieval call.

### `make eval`

```bash
docker compose up -d postgres   # same prerequisite as `make test`
make eval                        # uv run python -m agentic_learning_platform.evals.run_eval
```

Writes `eval_results/baseline_vector_only.v1.json` and prints a
human-readable summary to the terminal. The output path is named after the
retrieval strategy it measures — not a generic `eval_results.json` — so a
future PR-006 run writes its own `eval_results/hybrid_retrieval.v1.json`
alongside it instead of silently overwriting this baseline (flagged in code
review: a generic filename would have made exactly that overwrite the
default behavior). `config.retrieval_strategy` inside the JSON (currently
always `"vector_only"`) is the field a future comparison script would key
on; the top-level `baseline` field is kept as a human-friendly duplicate of
the same value.

Before running, the harness validates `retrieval_top_k >= 5` and fails fast
with `EvalConfigurationError` if not — this report always computes
Recall@5, which a lower `retrieval_top_k` would silently cap (e.g. at
whatever Recall@3 already measures), misrepresenting it as a genuine top-5
result.

### Tests vs. evals

`tests/evals/test_metrics.py`, `tests/evals/test_dataset.py`, and
`tests/evals/test_runner_validation.py` test the harness's own arithmetic,
the shipped dataset's schema, and the pre-flight `retrieval_top_k` guard —
small, hand-built fixtures, no DB, no retrieval. The 32 golden questions
themselves are **not** pytest assertions: they measure RAG quality, which
drifts and is judged by degree, not software correctness, which either
holds or doesn't.

### What this baseline found (reported, not fixed)

**Before** the categories B/C rewrite below: Recall@1 = 0.923, Recall@3 =
1.0, Recall@5 = 1.0, MRR = 0.962, Citation Accuracy = 1.0.

An adversarial review found that the original B ("paraphrase") and C
("related terms") questions retained substantial literal overlap with the
source text, making them a weak test of genuine semantic-only retrieval.
All 8 were rewritten by semantic intent alone, `expected_source`/
`expected_pages` re-verified and left unchanged, and the evaluator run
**exactly once** against the rewritten dataset — the questions were not
revisited afterward based on the resulting scores.

**After**: **Recall@1 = 0.846 (22/26), Recall@3 = 0.962 (25/26), Recall@5 =
0.962 (25/26), MRR = 0.904, Citation Accuracy = 0.962** — all four metrics
**dropped** relative to the flawed dataset. Four cases, not two, now miss
rank 1:

- `D1-incident-ambiguous`, `D2-problem-ambiguous` — unchanged from before
  (rank 2, recovered by Recall@3), see the D1/D2 analysis above.
- `C2-support-tiers-synonym` (new) — rank 2: *"Cuando la persona que atiende
  un caso no logra resolverlo, ¿a quién se lo transfiere para que alguien
  con mayor experiencia lo intente?"* scored 0.3829 against
  `itsm_glossary.pdf` p.2 (Problem Management) vs. 0.3161 against the
  expected `sla_and_support.pdf` p.1 — recovered by Recall@3.
- `C1-sla-synonym` (new, and the most significant finding) — **rank not
  found at all within top-5**: *"¿Qué compromiso formal establece qué tan
  rápido debe atenderse a quien reporta una falla?"* never retrieves the
  actual SLA page (`itsm_glossary.pdf` p.4) in the top 5 results; the
  system instead ranks Problem Management (0.4822), Incident Management
  (0.4702), the Security Policy (0.4368), and Support Tiers (0.3569) all
  higher, and confidently reports `has_sufficient_evidence=True` — the one
  wrong citation in this run (`citation_correct=False`). This is a genuine,
  not cosmetic, retrieval miss on a paraphrase that never uses the source's
  own SLA-specific vocabulary. **Not corrected** — this is precisely the
  kind of case Hybrid Retrieval (PR-006) should be measured against.

Every other category (A-direct, F-distractor, G-cross-course,
H-cross-organization) is completely unchanged and still ranks correctly at
position 1; No-Evidence Accuracy, False Positive/Negative Rate, and
Groundedness are all unchanged (`1.0`/`0.0`/`0.0`/`1.0`). Per this PR's
explicit mandate, both the before and after numbers are reported as-is —
**no retrieval/ranking code was touched, and the questions were not tuned
after seeing the drop**.

### Explicitly out of scope for PR-005

BM25, RRF, reranking, Hybrid Retrieval, LangGraph, an `IAnswerQualityPort`/
LLM-as-judge abstraction (deferred until real generation exists to design it
against), real Bedrock, S3, Terraform, AWS deployment, Cognito/JWT, any
widget/UX change, and any retrieval tuning aimed at improving the numbers
above.
