# Agentic Learning Platform

Backend for an AI Learning Assistant. **PR-002 — Local RAG flow**: upload a
PDF, ask a question, get an answer with a verifiable page citation, running
on PostgreSQL + pgvector. See [`docs/architecture.md`](docs/architecture.md)
for the reasoning behind what is (and is not) here.

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

Run the local demo end-to-end (upload + a question with a citation + a
question with no evidence):

```bash
./scripts/demo_local.sh
```

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

## Project status

Implemented: PDF parsing (Docling, digital text only, no OCR), page-based
chunking, embeddings (local or Bedrock), PostgreSQL + pgvector storage and
similarity search, question answering with citations, and the "insufficient
evidence" fallback. Deliberately **not** implemented yet: LangGraph, the
embeddable widget, streaming, authentication, multi-tenancy, S3, Terraform,
DOCX/PPTX/XLSX, diagrams, video, and Bedrock Knowledge Bases. These arrive in
later, separately reviewed PRs.

## License

[MIT](LICENSE)
