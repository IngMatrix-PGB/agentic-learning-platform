# Agentic Learning Platform

An AI Learning Assistant backend for e-learning platforms: students ask a
question about official course material and get an answer backed by a
verifiable citation (source file, page) — or an explicit "insufficient
evidence" response when the course material doesn't support an answer.
Answers are never generated from the model's general knowledge, only from
retrieved, cited course content.

This repository is a personal, open-source engineering project. It has
grown through a sequence of reviewed, incremental PRs (PR-001 through
PR-009) plus two formally recorded experiments (documented as ADRs) that
were evaluated and — in one case — rejected and reverted. That evolution,
including the parts that didn't work, is the point of the project: see
[`docs/architecture.md`](docs/architecture.md) for the full PR-by-PR
narrative, [`docs/adr/`](docs/adr/) for the two decision records, and
[`infra/README.md`](infra/README.md) for the infrastructure-as-code
status below.

**Current boundary, stated up front:** the RAG pipeline, LangGraph
orchestration, multi-tenant isolation, and evaluation framework run and are
validated locally. AWS integration (Bedrock, S3) is implemented in code but
has never been executed against a real AWS account. Terraform
infrastructure (PR-009) is written and reviewed but `terraform apply` has
never been run — no AWS resources have been provisioned by this
configuration. Details in the sections below.

## Architecture

Hexagonal architecture (ports/adapters): `domain/` (framework-free models),
`application/` (services, ports, the LangGraph workflow), `infrastructure/`
(concrete adapters — embeddings, vector store, document parsing, answer
generation, storage), `routes/` (FastAPI HTTP layer). Every capability with
more than one real implementation (embeddings, answer generation, document
storage) is behind a port, selected by one explicit `runtime_mode` setting
— `local` or `aws` — never auto-detected from credentials.

```
Client (widget / demo page)
   │  SSE or plain HTTP
   ▼
FastAPI routes  →  QueryService / IngestionService
   │
   ▼
LangGraph workflow (retrieve → evaluate_evidence → generate/abstain → build_citations)
   │
   ├── Embeddings   : FastEmbed (local)        or  Bedrock Titan Embed V2 (aws)
   ├── Answer gen.  : extractive (local)        or  Bedrock Claude 3.5 Haiku (aws)
   ├── Vector store : PostgreSQL + pgvector      (both modes)
   └── Doc storage  : none (local)               or  S3 (aws)
```

Local mode needs nothing but Docker — no AWS account, no credentials. AWS
mode swaps three adapters (embeddings, answer generation, document storage)
behind the same ports and the same LangGraph workflow; see "AWS Adapters"
below for what that mode has and has not been validated against.

## Local RAG: PDF → Question → Cited Answer — IMPLEMENTED AND LOCALLY VALIDATED

Upload a PDF, ask a question, get an answer with a page citation, or the
fixed "insufficient evidence" message when nothing in the corpus clears the
retrieval-score threshold. Parsing is Docling (digital text only, no OCR),
chunked by page, embedded (locally with FastEmbed, multilingual,
384-dimension), stored in PostgreSQL + pgvector, retrieved by cosine
similarity. This is the part of the system exercised directly by the test
suite and the local demo (`./scripts/demo_local.sh` — see "Running Locally"
below).

## Multi-Tenant Isolation

Every document and every query is scoped to an `organization_id` +
`course_id`, enforced at the query layer (composite keys, `WHERE`-scoped
retrieval, a foreign key tying each chunk's scope to its parent document) —
verified by an adversarial test that uploads byte-identical PDFs into three
different org/course combinations and asserts the retrieved chunks never
cross scope boundaries.

The scope itself is currently resolved from `X-Organization-Id` /
`X-Course-Id` / `X-User-Id` request headers — a **development authorization
context, not real authentication**. Any client can set any value; there is
no verification of who is asking. This is deliberate for the current stage
(see `docs/architecture.md`), not an oversight, and it's the top item under
"Next / Deferred Work" below.

## Evaluation-Driven Engineering

Retrieval quality is measured, not assumed. `make eval` runs a 32-case
golden dataset (`eval_data/golden_dataset.v1.json`) through the real,
unmodified production `RetrievalService`/`QueryService`/LangGraph workflow
against a dedicated, disposable database, and reports Recall@1/3/5, MRR,
Citation Accuracy, No-Evidence Accuracy, and retrieval latency — never
tuned to the dataset, only measured against it. Current baseline
(`eval_results/baseline_vector_only.v1.json`): Recall@1 0.846, Recall@3
0.962, Recall@5 0.962, MRR 0.904, Citation Accuracy 0.962. This same
framework, not intuition, is what backed the two engineering decisions
below.

## Engineering Decisions: What We Tried and Rejected

Two retrieval-quality experiments were run against the baseline above and
recorded as formal Architecture Decision Records. Both are still
authoritative for the current production retrieval path.

**[ADR-0001 — Hybrid Retrieval](docs/adr/0001-hybrid-retrieval-rejected.md):**
vector + PostgreSQL full-text search, fused with Reciprocal Rank Fusion,
was **implemented, evaluated, rejected, and reverted**. It produced
*exactly* the same Recall@1/3/5, MRR, and Citation Accuracy as vector-only
retrieval — no measurable improvement on any quality metric — while adding
roughly +43% p95 retrieval latency (8.07ms → 11.43ms). The one case it was
meant to fix wasn't found by either the vector or the lexical side, so
fusing two rankings that both miss the right document couldn't produce it.
Decision: **KEEP VECTOR_ONLY** — the hybrid runtime is not part of `main`.

**[ADR-0002 — E5 Retrieval Adoption](docs/adr/0002-e5-retrieval-adoption-deferred.md):**
swapping the embedding model to E5 showed a real, measured retrieval-ranking
improvement **on this evaluation corpus** (Recall@1 0.846→0.885, MRR
0.904→0.936). That result is a **GO for ranking quality on this corpus** —
it is *not* a claim that E5 is production-ready or that it improves the
system globally. Three separate approaches to gating E5's answers on
retrieval confidence (an absolute score threshold, a score-margin gate, and
a cross-encoder verifier) were then evaluated against held-out validation
data, and **all three failed their predefined GO criteria** — false-positive
rates 6x higher on validation than on calibration, or near-zero true-positive
rates, or a cross-encoder that would have rejected the correct evidence in
every one of its headline test cases. **Evidence gating is not a solved
problem** in this repository under the criteria tested. Decision: **DEFER
E5 adoption** — production retrieval is unchanged (`paraphrase-multilingual
-MiniLM-L12-v2`, 384 dimensions, vector-only, threshold 0.35).

## LangGraph Orchestration — IMPLEMENTED AND LOCALLY VALIDATED

A single compiled `StateGraph` (`retrieve → evaluate_evidence →` either
`generate → build_citations` or `abstain` `→ END`) is the one orchestration
path for both request styles: `/v1/query` calls it with `ainvoke()`
(buffered), `/v1/query/stream` calls the same graph with `astream()`
(progressive, via LangGraph's stream-writer mechanism) — one business logic
implementation, two delivery mechanisms, never two parallel workflows. No
checkpointer, no persisted conversational state, no multi-agent behavior.
`make eval` reproduces the pre-LangGraph baseline bit-for-bit, which is the
regression test for this refactor.

## AWS Adapters — IMPLEMENTED IN CODE, NOT VALIDATED AGAINST REAL AWS

`runtime_mode=aws` swaps in three adapters behind the same ports used by
local mode:

- **Amazon Titan Embed Text V2** embeddings (1024 dimensions).
- **Anthropic Claude 3.5 Haiku via Bedrock**, using `ChatBedrockConverse` —
  including **real per-token streaming** (`.astream()`, not a paced replay
  of a complete answer) for `/v1/query/stream`, plus token/latency/cost
  logging.
- **S3** for private source-document storage (upload/delete only).

All three are implemented, unit-tested, and covered by an opt-in
integration suite (`tests/aws_smoke/`, gated behind `RUN_AWS_SMOKE_TESTS=1`
and real AWS credentials) — but that suite has never been run in this
project: it is not part of CI, and no AWS credentials have been used
against this code. **None of the three adapters above has been executed
against a real Bedrock or S3 endpoint.** Standard AWS SDK credential chain
only — no static credentials anywhere in this repository.

## Infrastructure as Code — WRITTEN AND REVIEWED, NEVER APPLIED

[`infra/`](infra/README.md) contains Terraform for a dev-pilot AWS
deployment (PR-009): a bootstrap remote-state module, and five
purpose-scoped modules — networking (VPC, ALB, NAT, security groups),
database (RDS PostgreSQL, pgvector-capable), storage (private S3 bucket),
IAM (least-privilege execution/task roles), and ECS (Fargate service,
ECR, CloudWatch Logs, Secrets Manager wiring for the RDS credential). It
went through an explicit adversarial-review → fix-round → final-review
cycle (`terraform validate` and Checkov clean, documented findings for
everything intentionally deferred).

**`terraform apply` has never been run for this infrastructure in this
project.** No AWS resources have been provisioned by this Terraform
configuration — no VPC, no database, no ECS service, nothing live. The
backend configuration still points at a placeholder state bucket, and
`infra/README.md` documents three explicit pre-apply gates that remain
unverified against a real target account (PostgreSQL engine-version
availability, the exact Bedrock model/inference-profile ARN shape, and
whether the RDS master user can run the required pgvector extension
migration in that account) — none of this is presented as solved.

## Current Boundary / Limitations

- **No real authentication.** Org/course/user scope comes from trusted
  request headers, not a verified identity.
- **No Postgres Row-Level Security** — isolation is enforced at the query
  layer (see "Multi-Tenant Isolation"), not by database policy.
- **AWS adapters are unvalidated against real AWS** (see above).
- **No AWS deployment exists** — Terraform is written, not applied.
- **TLS/HTTPS ingress is deferred** in the Terraform design itself — the
  reviewed pilot architecture uses HTTP behind an IP-restricted ALB, with
  TLS/domain acquisition explicitly left for later work.
- **No production observability** beyond structured JSON logs and Bedrock
  cost/token logging — no distributed tracing, no alarms/dashboards.
- The chat widget has not been tested inside a host page with a strict
  Content-Security-Policy.
- Evidence gating beyond a single scalar similarity threshold is not a
  solved problem here (see ADR-0002).

## Next / Deferred Work

Derived from what's currently documented as open in `docs/architecture.md`
and `infra/README.md`, not from an aspirational roadmap:

- Real authentication (JWT/OIDC) replacing the dev-header trust model.
- Resolving the three Terraform pre-apply gates above, then an actual
  `terraform apply` and a first real AWS smoke-test run.
- Splitting the RDS credential model (the same privileged credential
  currently runs both schema migrations and normal application traffic).
- A TLS/domain decision for public ingress.
- Production observability (alarms, dashboards, tracing) and autoscaling —
  none of this exists today, by design, for a single-instance pilot.

---

## Running Locally

### Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker + Docker Compose

### Setup

```bash
uv sync
cp .env.example .env
```

This creates a `.venv`, installs runtime and development dependencies from
`uv.lock`, and copies the default (non-secret) local configuration.

### Running the full stack (recommended)

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
  Events (see "Widget, Demo Page and Streaming" below).

All three above **require** `X-Organization-Id`, `X-Course-Id`, and
`X-User-Id` headers — see "Multi-Tenant Isolation" above. Missing or blank
headers return `401`.

- `GET /demo/` — the demo course page with the embedded widget.

Run the local demo end-to-end (upload + a question with a citation + a
question with no evidence):

```bash
./scripts/demo_local.sh
```

Then open http://localhost:8000/demo/ in a browser and ask a question to
see the widget/streaming flow.

### Running locally without Docker

Requires `postgres` running separately (e.g. `docker compose up -d postgres`
and set `DB_HOST=localhost` in `.env`, which is already the default there):

```bash
make run
```

### Runtime mode

`RUNTIME_MODE` in `.env` — explicit, never auto-detected:

- `local` (default): FastEmbed multilingual embeddings (in-process, no AWS
  needed) + an extractive answer "generator" (returns the retrieved
  fragment(s) verbatim — demonstrates parsing/chunking/retrieval/citations,
  not LLM answer quality).
- `aws`: Bedrock Titan V2 embeddings + Bedrock Claude 3.5 Haiku generation
  with real streaming. Requires real AWS credentials with Bedrock access
  and `EMBEDDING_DIMENSION=1024` set **before** the first migration runs
  against a given database — see "AWS Adapters" above for what has and has
  not been validated in this mode, and `docs/architecture.md` for why the
  dimension is fixed at migration time.

## Running Tests and Evaluations

```bash
make lint       # ruff check
make format     # ruff format
make typecheck  # pyright (strict mode)
make test       # pytest (needs a running postgres)
make check      # lint + typecheck + test
```

`pytest` runs against its own ephemeral database, separate from whatever
`./scripts/demo_local.sh`/`/demo/` puts into the regular demo database — no
manual reset needed between the two. `tests/aws_smoke/` (real-AWS
integration tests) are excluded from this run by default; see "AWS
Adapters" above for why.

```bash
docker compose up -d postgres   # same prerequisite as `make test`
make eval
```

Measures (never tunes) current RAG quality against the golden dataset — see
"Evaluation-Driven Engineering" above. This harness is run manually; it is
not currently part of CI.

## Widget, Demo Page and Streaming

`GET /demo` serves a small page simulating an e-learning course
(`web/demo/index.html`) that embeds `<learning-assistant-widget>`
(`web/widget/widget.js`) — a vanilla-JS Web Component (Shadow DOM, no
framework, no build step). It opens as a side panel, keeps its conversation
history in memory for the page's lifetime, and consumes
`POST /v1/query/stream` via `fetch()` + a manually-parsed `ReadableStream`
(not the native `EventSource`, which cannot send a POST body).

### Streaming contract

`POST /v1/query/stream` takes the same request body as `/v1/query`
(`{"question": "..."}`, same length validation) and responds
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

- **Local mode** paces a complete answer out word-by-word
  (`STREAM_CHUNK_DELAY_MS`, default 40ms) to demonstrate the protocol —
  `ExtractiveAnswerGeneratorAdapter` has no real incremental generation of
  its own.
- **AWS mode streams real, incremental tokens** from Bedrock as they're
  generated (`ChatBedrockConverse.astream()` via the LangGraph workflow's
  stream-writer) — this is implemented and unit-tested, but see "AWS
  Adapters" above: it has never been exercised against a real Bedrock
  endpoint in this project.
- Once the stream has started (HTTP 200 already sent), a failure inside the
  graph surfaces as an in-band `event: error` frame rather than a clean
  HTTP error status — a deliberate, documented trade-off of adding real
  streaming; see `docs/architecture.md`.
- SSE, not WebSockets: there is no bidirectional need here, and
  `EventSource` can't send a POST body, hence manual `fetch()`-based
  parsing instead.

### CORS

Configured explicitly via `CORS_ALLOWED_ORIGINS` (comma-separated origins,
default `http://localhost:8000`) — **never** `allow_origins=["*"]`. The
`/demo` page is served by this same app and never needs CORS; this exists
for the widget being embedded on a different origin, and the shipped
default is for local development only.

### Input limits

`MAX_QUESTION_LENGTH` (default 2000) applies identically to `/v1/query` and
`/v1/query/stream` — one shared `QueryRequest` model, one limit.

## Repository Structure

```
src/agentic_learning_platform/
  domain/             framework-free models
  application/        services, ports, the LangGraph workflow
  infrastructure/     concrete adapters (embeddings, vector store, parsing,
                      answer generation, storage, DB migrations)
  routes/             FastAPI HTTP layer
tests/                pytest suite (excludes tests/aws_smoke/ by default)
evals/, eval_data/,   the evaluation harness, golden dataset, and every
eval_results/         recorded eval/experiment result (baseline + ADR data)
docs/
  architecture.md     PR-by-PR engineering narrative
  adr/                ADR-0001 (hybrid retrieval), ADR-0002 (E5)
infra/                Terraform for PR-009 (see "Infrastructure as Code")
web/                  demo page + embeddable widget
```

## License

[MIT](LICENSE)
