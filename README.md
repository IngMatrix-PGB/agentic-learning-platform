# Agentic Learning Platform

Backend for an AI Learning Assistant. **PR-002 — Local RAG flow**: upload a
PDF, ask a question, get an answer with a verifiable page citation, running
on PostgreSQL + pgvector. **PR-003 — Embeddable chat widget + streaming**:
a small embeddable widget and a demo course page consume the RAG flow
progressively over Server-Sent Events. See
[`docs/architecture.md`](docs/architecture.md) for the reasoning behind what
is (and is not) here.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker + Docker Compose

## Setup

```bash
uv sync
cp .env.example .env
```

This creates a `.venv`, installs runtime and development dependencies from
`uv.lock`, and copies the default (non-secret) local configuration.

## Running the full stack (recommended)

```bash
docker compose up --build -d
```

This starts `postgres` (with the `pgvector` extension) and the `api`
service. The API applies its own migrations on startup. The first run also
downloads the local embedding model (~0.2GB) into a persistent Docker
volume — later runs reuse it, no internet access needed after that.

- `GET /health` — liveness probe.
- `GET /ready` — readiness probe; verifies the database is actually reachable.
- `POST /v1/documents` — upload a PDF (multipart `file` field).
- `POST /v1/query` — `{"question": "..."}` → `{"answer": "...", "citations": [...]}`.
- `POST /v1/query/stream` — same question, answer paced over Server-Sent
  Events (see "Widget, demo page and streaming" below).
- `GET /demo/` — the demo course page with the embedded widget (`GET /demo`
  without the trailing slash also works — `StaticFiles` responds with a
  `307` redirect to `/demo/`).

Run the local demo end-to-end (upload + a question with a citation + a
question with no evidence):

```bash
./scripts/demo_local.sh
```

Then open http://localhost:8000/demo/ in a browser, click "Pregúntale al
Tutor", and ask the same two questions to see the widget/streaming flow —
see "Widget, demo page and streaming" below for the full manual walkthrough.

## Widget, demo page and streaming

`GET /demo` serves a small page simulating an e-learning course
(`web/demo/index.html`) that embeds `<learning-assistant-widget>`
(`web/widget/widget.js`) — a vanilla-JS Web Component (Shadow DOM, no
framework, no build step). It opens as a side panel, keeps its conversation
history in memory for the page's lifetime, and consumes
`POST /v1/query/stream` via `fetch()` + a manually-parsed `ReadableStream`
(not the native `EventSource`, which cannot send a POST body).

**Manual demo walkthrough:**

1. `docker compose up --build -d`
2. `./scripts/demo_local.sh` (uploads the synthetic demo PDF)
3. Open http://localhost:8000/demo/
4. Click "Pregúntale al Tutor"
5. Ask a question from the PDF's content (e.g. "¿Qué es la gestión de
   incidentes?") — the answer should appear progressively, followed by
   "Fuente: manual.pdf, página 1" (or wherever the demo PDF was ingested from)
6. Ask an out-of-scope question (e.g. "¿Cómo se prepara una paella
   valenciana?") — expect the fixed "insufficient evidence" message, no
   citations
7. Check the browser console — no errors expected
8. `docker compose down`

### Streaming contract

`POST /v1/query/stream` takes the same request body as `/v1/query`
(`{"question": "..."}`, same length validation — see below) and responds
`200 text/event-stream`:

```text
event: token
data: {"text": "No hay "}

event: token
data: {"text": "información..."}

event: citations
data: {"citations": [{"source": "manual.pdf", "page": 1, "chunk_id": "...", "score": 0.87}]}

event: done
data: {}
```

- The full `QueryAnswer` (retrieval, evidence check, generation, citations)
  is computed **before** the stream opens — a retrieval/generation/
  infrastructure error, or a validation error, produces a normal HTTP error
  status, never a broken stream. `event: error` exists only as a defensive
  fallback for a failure during emission itself (e.g. the client
  disconnecting mid-stream).
- **Local mode demonstrates the streaming protocol/UX, not real model
  streaming**: `ExtractiveAnswerGeneratorAdapter` returns the full answer at
  once; the route paces it out word-by-word (`STREAM_CHUNK_DELAY_MS`,
  default 40ms) purely to demonstrate the contract. **`aws` mode currently
  does the same** — `BedrockAnswerGeneratorAdapter` uses `ainvoke`, not
  `astream`, in this PR. Real token-by-token streaming from Bedrock is a
  future PR that would add a streaming method to `IAnswerGeneratorPort`.
- SSE (not WebSockets): there is no bidirectional need here. The widget uses
  `fetch()` + manual SSE parsing rather than the native `EventSource`,
  because `EventSource` only supports `GET` with no request body — putting
  the question in a query string instead would leak it into server logs/URLs
  and fight the question-length limit below.

### CORS

Configured explicitly via `CORS_ALLOWED_ORIGINS` (comma-separated origins,
default `http://localhost:8000`) — **never** `allow_origins=["*"]`. The
`/demo` page is served by this same app and never needs CORS; this exists
for the widget being embedded on a different origin (a real client portal),
and the shipped default is for local development only — set the real origin
before deploying.

### Input limits

`MAX_QUESTION_LENGTH` (default 2000) applies identically to `/v1/query` and
`/v1/query/stream` — one shared `QueryRequest` model, one limit, not two
independently-drifting ones.

### Known limitations

- No authentication yet (explicitly out of scope for this PR — see
  `docs/architecture.md`); a real client portal integration needs it before
  going further than a local demo.
- The widget has not been tested inside a host page with a strict
  Content-Security-Policy; a CSP that blocks external scripts would need an
  allowance for the widget's `<script src>`.

## Running locally without Docker

Requires `postgres` running separately (e.g. `docker compose up -d postgres`
and set `DB_HOST=localhost` in `.env`, which is already the default there):

```bash
make run
```

## Execution modes

`RUNTIME_MODE` in `.env` — explicit, never auto-detected:

- `local` (default): FastEmbed multilingual embeddings (in-process, no AWS
  needed) + an extractive answer "generator" (returns the retrieved
  fragment(s) verbatim — demonstrates parsing/chunking/retrieval/citations,
  not LLM answer quality).
- `aws`: AWS Bedrock Titan embeddings + `ChatBedrockConverse` generation.
  Requires AWS credentials with Bedrock access and
  `EMBEDDING_DIMENSION=1024` set **before** the first migration runs against
  a given database (see `docs/architecture.md` — the dimension is validated
  at startup and cannot be changed against an existing database).

## Development

```bash
make lint       # ruff check
make format     # ruff format
make typecheck  # pyright (strict mode)
make test       # pytest (needs a running postgres — see above)
make check      # lint + typecheck + test
```

**⚠️ Tests and the manual demo currently share the same local PostgreSQL
instance** (no per-run isolation yet — see `docs/architecture.md`'s known
limitations). Running `./scripts/demo_local.sh` or clicking around `/demo/`
ingests documents into the same database `pytest` queries against; a
leftover document with similar content can make an unrelated test's citation
assertions fail. Before running the test suite from a known-clean state:

```bash
docker compose down -v
docker compose up -d postgres
```

`down -v` **destroys all local Postgres/FastEmbed data in the Docker
volumes** — only ever run this in your local dev/demo environment, never
against a shared or persistent database. Proper corpus isolation (per
document/tenant, or a dedicated test database) is deferred to a future PR.

## Project status

Implemented: PDF parsing (Docling, digital text only, no OCR), page-based
chunking, embeddings (local or Bedrock), PostgreSQL + pgvector storage and
similarity search, question answering with citations, the "insufficient
evidence" fallback, an embeddable chat widget, a demo course page, and
streaming (transport-level pacing, not real model streaming — see above).
Deliberately **not** implemented yet: LangGraph, real Bedrock token
streaming, authentication, multi-tenancy, S3, Terraform, DOCX/PPTX/XLSX,
diagrams, video, and Bedrock Knowledge Bases. These arrive in later,
separately reviewed PRs.

## License

[MIT](LICENSE)
